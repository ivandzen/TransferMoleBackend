import logging
from fastapi import Request, APIRouter
from stripe import Webhook, error, BalanceTransaction, SignatureVerificationError
from typing import Tuple
from psycopg2.extensions import cursor
import datetime
from decimal import Decimal
import json

from ..common.config import Config
from ..notification import VerificationComplete
from ..notification_utils import send_notification
from ..payment import Payment
from ..payment_processor import update_payment
from ..currency import Currency
from ..payout.account_factory import AccountFactory
from ..verification.stripe_account import StripeAccount, StripeUpdateAccountEventData
from ..creator_loader import CreatorLoader
from ..common.database import Database

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stripe", tags=["stripe_webhook"])


class StripeWebhookError(Exception):
    def __init__(self, msg: str):
        Exception.__init__(self, msg)


def checkout_session_completed(data: dict, _created: datetime.datetime, cur: cursor) -> None:
    obj = data.get('object', None)
    if obj is None:
        raise StripeWebhookError(f"Failed to get checkout session object: {json.dumps(data)}")

    session_id = obj.get('id', None)
    if session_id is None:
        raise StripeWebhookError(f"Failed to get checkout session id: {json.dumps(data)}")

    payment_intent = obj.get('payment_intent', None)
    if payment_intent is None:
        raise StripeWebhookError(f"Failed to get payment intent from checkout session: {session_id}")

    amount_str = obj.get('amount_total', None)
    try:
        amount_dec = Decimal(amount_str)
    except Exception as _:
        raise StripeWebhookError(f"Wrong amount: {amount_str}")

    logger.info(f"Checkout session {session_id} completed")
    card_payment = Payment.get_stripe_payment_by_checkout_session(session_id, cur)
    update_payment(
        card_payment, cur,
        total_amount=amount_dec / 100,
        to_usd_rate=Currency.get_exchange_rate_to_usd(card_payment.currency),
        external_id=payment_intent,
        status='payment complete',
        tm_fee=Decimal(Config.TRANSFERMOLE_FEE_USD) / Decimal(100),
    )


def checkout_session_expired(data: dict, _created: datetime.datetime, cur: cursor) -> None:
    obj = data.get('object', None)
    if obj is None:
        raise StripeWebhookError(f"Failed to get checkout session object: {json.dumps(data)}")

    session_id = obj.get('id', None)
    if session_id is None:
        raise StripeWebhookError(f"Failed to get checkout session id: {json.dumps(data)}")

    logger.info(f"Checkout session {session_id} expired")

    card_payment = Payment.get_stripe_payment_by_checkout_session(session_id, cur)
    update_payment(card_payment, cur, status='expired')


def payout_paid(data: dict, _created: datetime.datetime, cur: cursor) -> None:
    obj: dict = data.get('object', None)
    if not isinstance(obj, dict):
        raise StripeWebhookError(f"Failed to get payout object: {json.dumps(data)}")

    destination = obj.get('destination', None)
    if destination is None:
        raise StripeWebhookError(f"Failed to get payout object destination: {json.dumps(data)}")

    payout_id = obj.get('id', None)
    if payout_id is None:
        raise StripeWebhookError(f"Failed to get payout id: {json.dumps(data)}")

    stripe_bank_acc = AccountFactory.get_stripe_bank_account(destination, cur)
    balance_req_params = {
        'expand': ['data.source'],
        'payout': payout_id,
    }

    transactions = BalanceTransaction.list(
        api_key=Config.STRIPE_USER,
        stripe_account=stripe_bank_acc.stripe_account,
        **balance_req_params
    )

    transactions_data = transactions.get('data', None)
    if transactions_data is None:
        raise StripeWebhookError(f"Transactions response does not contain 'data' field: {transactions}")

    payment_intents = []
    for transaction in transactions_data:
        source = transaction.get('source', None)
        if source is None:
            raise StripeWebhookError(f"Transaction does not contain source field: {transaction}")

        object_field = source.get('object', None)
        if object_field is None:
            raise StripeWebhookError(f"Source does not contain object field: {source}")

        if object_field == 'charge':
            payment_intent = source.get('payment_intent', None)
            if payment_intent is None:
                logger.warning(f"Source does not contain 'payment_intent' field: {source}")
                continue
            payment_intents.append(payment_intent)
        elif object == 'payout':
            arrival_date = source.get('arrival_date', None)
            if arrival_date is None:
                logger.warning(f"Source does not contain 'arrival_date' field: {source}")
                continue

    logger.info(f"Total stripe payments paid out: {len(payment_intents)}")
    Payment.stripe_payment_intents_completed(payment_intents, cur)


def account_updated(data_dict: dict, event_time: datetime.datetime, cur: cursor) -> None:
    data = StripeUpdateAccountEventData.model_validate(data_dict)
    logger.info(f"Stripe account {data.object.id} updated")
    stripe_account = StripeAccount.load(data.object.id, cur)
    if stripe_account is None:
        raise StripeWebhookError(f"Stripe account {data.object.id} not found")

    if stripe_account.last_event_time is not None and event_time < stripe_account.last_event_time:
        return

    individual = data.object.individual
    creator = CreatorLoader.get_creator_by_id(stripe_account.creator_id, cur)
    if not creator:
        logger.error(f"Creator {stripe_account.creator_id} not found")
        return

    if not creator.country:
        logger.error(f"Country not set for creator {creator.creator_id} but account verified!")
        return

    if not creator.personal_info:
        logger.error(f"Creator {creator.creator_id} has no personal_into set")
        return

    if stripe_account.verification_status != "verified" and individual.verification.status == "verified":
        send_notification(creator.creator_id, VerificationComplete(verification_provider="Stripe"), None)
        bank_accounts = AccountFactory.get_creator_stripe_bank_accounts(creator, cur)
        for bank_acc in bank_accounts:
            logger.info(f"Creating stripe bank account for {bank_acc.payout_channel.channel_id}")
            bank_acc.create_stripe_bank_account(
                stripe_account=stripe_account.account_id,
                stripe_test_mode=not Config.PRODUCTION,
                bank_requirements=creator.country.get_bank_account_requirements(),
                cur=cur
            )

    stripe_account.set_verification_status(
        individual.verification.status == "verified",
        individual.requirements,
        event_time,
        cur
    )

    updated_personal_info = creator.personal_info
    updated_personal_info.update(
        creator.country.check_personal_info(
            data_dict["object"]["individual"],
            soft_mode=True
        )
    )

    creator.update_personal_info(updated_personal_info, cur)


def transfer_created(data: dict, event_time: datetime.datetime, cur: cursor) -> None:
    obj: dict = data.get('object', None)
    if not isinstance(obj, dict):
        raise StripeWebhookError(f"Failed to get account object: {json.dumps(data)}")

    transfer_id = obj.get("id", None)
    if transfer_id is None:
        raise StripeWebhookError(f"Failed to get transfer id: {json.dumps(data)}")


processors = {
    'checkout.session.completed': checkout_session_completed,
    'checkout.session.expired': checkout_session_expired,
    'payout.paid': payout_paid,
    'account.updated': account_updated,
    'transfer.created': transfer_created,
}


async def webhook_get(request: Request, secret: str) -> Tuple[str, int]:
    try:
        payload = (await request.body()).decode("utf-8")
        received_sig = request.headers.get("Stripe-Signature", None)
        event = Webhook.construct_event(
            payload, received_sig, secret
        )
    except ValueError:
        logger.warning("Error while decoding event!")
        return "Bad payload", 400
    except SignatureVerificationError:
        logger.warning("Invalid signature!")
        return "Failed to check webhook signature", 400

    logger.info(
        "Received stripe event (GET): id={id}, type={type}".format(
            id=event.id, type=event.type
        )
    )

    return "", 200


async def webhook_post(request: Request, webhook_secret: str) -> Tuple[str, int]:
    try:
        payload = (await request.body()).decode("utf-8")
        received_sig = request.headers.get("Stripe-Signature", None)
        event = Webhook.construct_event(
            payload, received_sig, webhook_secret
        )
    except ValueError:
        logger.warning("Error while decoding event!")
        return "Bad payload", 400
    except SignatureVerificationError:
        logger.warning("Invalid signature!")
        return "Failed to check webhook signature", 400

    cur = Database.begin()
    processor = processors.get(event.type, None)
    if processor is not None:
        try:
            processor(event.data, datetime.datetime.fromtimestamp(event.created), cur)
            Database.commit()
            return "", 200
        except Exception as e:
            logger.error(f"Error: {e.__str__()}")
            return e.__str__(), 500

    return "", 200


@router.get("/connect_webhook")
async def connect_webhook_get(request: Request) -> Tuple[str, int]:
    return await webhook_get(request, Config.STRIPE_CONNECT_WEBHOOK_SECRET)


@router.get("/account_webhook")
async def account_webhook_get(request: Request) -> Tuple[str, int]:
    return await webhook_get(request, Config.STRIPE_ACCOUNT_WEBHOOK_SECRET)


@router.post("/connect_webhook")
async def connect_webhook_post(request: Request) -> Tuple[str, int]:
    return await webhook_post(request, Config.STRIPE_CONNECT_WEBHOOK_SECRET)


@router.post("/account_webhook")
async def account_webhook_post(request: Request) -> Tuple[str, int]:
    return await webhook_post(request, Config.STRIPE_ACCOUNT_WEBHOOK_SECRET)
