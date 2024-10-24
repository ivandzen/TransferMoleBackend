import datetime
import logging
import uuid
from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from decimal import Decimal
from typing import Literal, Optional, Annotated
from psycopg2.extensions import cursor
import hashlib
import hmac

from ..common.api_error import APIError
from ..common.config import Config
from ..payment_processor import update_payment
from ..payment import Payment
from .common import database_cursor
from ..currency import Currency, convert_currency_to_usd
from ..transfer import Transfer
from ..verification.mercuryo_user import MercuryoUser
from ..payout.account_factory import AccountFactory
from ..payout.providers.payout_provider_cache import PROVIDER_MERCURYO

logger = logging.getLogger(__name__)
router = APIRouter(prefix=f"/mercuryo", tags=["mercuryo_webhook"])


class UserData(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    uuid4: uuid.UUID
    country_code: str


class WebhookData(BaseModel):
    id: str
    fee: Optional[Decimal] = None
    rate: Optional[Decimal] = None
    type: Literal["buy", "sell", "withdraw", "deposit"]
    user: UserData
    amount: Optional[Decimal] = None
    status: Literal[
        "new", "pending", "cancelled", "paid", "order_failed", "order_scheduled", "order_verified_not_complete",
        "failed_exchange", "descriptor_failed", "succeeded", "failed", "completed"
    ]
    currency: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    fiat_amount: Optional[Decimal] = None
    partner_fee: Optional[Decimal] = None
    created_at_ts: int
    fiat_currency: str
    updated_at_ts: int
    payment_method: Optional[str] = None
    card_masked_pan: Optional[str] = None
    merchant_transaction_id: uuid.UUID


class WebhookPayload(BaseModel):
    data: WebhookData


async def get_webhook_payload(request: Request) -> WebhookPayload:
    signature = request.headers.get("x-signature", None)
    if not signature:
        raise APIError(
            APIError.INTERNAL,
            f"Signature header is absent in Mercuryo callback"
        )

    expected_signature = hmac.new(
        Config.MERCURYO_SIGN_KEY.encode('utf-8'),
        msg=await request.body(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if signature != expected_signature:
        raise APIError(
            APIError.INTERNAL,
            "Signature not match"
        )

    return WebhookPayload.model_validate(await request.json())


@router.post(path="/callback")
async def callback_handler(
        cur: Annotated[cursor, Depends(database_cursor)],
        payload: Annotated[WebhookPayload, Depends(get_webhook_payload)],
) -> None:
    logger.info(f"Mercuryo: {payload.data.type}.{payload.data.status} {payload.data.merchant_transaction_id}")
    if payload.data.type == "buy":
        await process_buy_event(payload, cur)
        return

    if payload.data.type == "withdraw":
        await process_withdraw_event(payload, cur)
        return

    raise APIError(
        APIError.INTERNAL,
        f"Events of type {payload.data.type} are not supported yet"
    )


def _set_transfer_status(transfer_id: uuid.UUID, status: str, cur: cursor) -> None:
    transfer = Transfer.get_by_id(transfer_id, cur)
    if transfer.status != status:
        transfer.set_status(status, cur)
    else:
        logger.error(f"Transfer {transfer_id} already {status}")


def _get_tm_fee(payload: WebhookPayload) -> None | Decimal:
    if payload.data.partner_fee:
        return convert_currency_to_usd(payload.data.partner_fee, payload.data.fiat_currency)

    return None


async def process_buy_event(payload: WebhookPayload, cur: cursor) -> None:
    MercuryoUser.get_or_create_new_empty(
        user_id=payload.data.user.uuid4,
        email=payload.data.user.email,
        phone=payload.data.user.phone,
        cur=cur
    )

    match payload.data.status:
        case "new":
            payment = Payment.load(payload.data.merchant_transaction_id, 0, cur)
            if payload.data.fiat_currency != payment.currency:
                logger.error(
                    f"Mercuryo payment {payload.data.id} currency is expected to be {payment.currency}"
                    f" but actually is {payload.data.fiat_currency}"
                )
                return

            update_payment(
                payment, cur,
                total_amount=payload.data.fiat_amount,
                to_usd_rate=Currency.get_exchange_rate_to_usd(payload.data.fiat_currency),
                external_id=payload.data.id,
                status='created',
                tm_fee=_get_tm_fee(payload),
            )

        case "paid":
            payment = Payment.load(payload.data.merchant_transaction_id, 0, cur)
            update_payment(
                payment, cur,
                total_amount=payload.data.fiat_amount,
                to_usd_rate=Currency.get_exchange_rate_to_usd(payload.data.fiat_currency),
                external_id=payload.data.id,
                status='paid',
                tm_fee=_get_tm_fee(payload),
            )

        case "cancelled":
            _set_transfer_status(
                transfer_id=payload.data.merchant_transaction_id,
                status='canceled',
                cur=cur
            )

        case "order_failed" | "failed_exchange" | "descriptor_failed":
            _set_transfer_status(
                transfer_id=payload.data.merchant_transaction_id,
                status='failed',
                cur=cur
            )

        case "pending" | "paid" | "order_scheduled" | "order_verified_not_complete": pass


async def process_withdraw_event(payload: WebhookPayload, cur: cursor) -> None:
    match payload.data.status:
        case "completed":
            transfer = Transfer.get_by_id(payload.data.merchant_transaction_id, cur)
            crypto_channel = AccountFactory.get_crypto_payout_channel(
                transfer.payments[0].payout_channel_id, cur, True
            )

            new_payment = transfer.create_payment(
                payment_type=f"crypto:{crypto_channel.data.network}",
                currency=payload.data.currency,
                sender_channel_id=None,
                recipient_channel_id=transfer.payments[0].payout_channel_id,
                provider=PROVIDER_MERCURYO.name,
                cur=cur,
            )

            update_payment(
                new_payment, cur,
                total_amount=payload.data.amount,
                to_usd_rate=Currency.get_exchange_rate_to_usd(payload.data.currency),
                external_id=payload.data.id,
                status='paid out',
            )

        case "failed":
            _set_transfer_status(
                transfer_id=payload.data.merchant_transaction_id,
                status='failed',
                cur=cur
            )
