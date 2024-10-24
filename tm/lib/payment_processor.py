import uuid
from psycopg2.extensions import cursor
import logging
from decimal import Decimal
from typing import Optional, List, Any
from dataclasses import dataclass

from .common.api_error import APIError
from .payment import Payment, UpdatePaymentParams
from .payout.payout_channel import PayoutChannel
from .transfer import Transfer
from .creator import Creator
from .payout.payment_intent import PaymentIntent
from .payout.termination_account import ProviderAccountType
from .payout.account_factory import AccountFactory
from .notification import TransferComplete, PayoutRequest
from .notification_utils import send_notification
from .authentication.auth_account import AuthAccount
from .currency import Currency
from .creator_loader import CreatorLoader
from .crypto_network import CRYPTO_PAYMENT_TYPES
from .currency import convert_currency_to_usd
from .currency import convert_usd_to_currency
from .verification.creator_verificator import CreatorVerificator

logger = logging.getLogger(__name__)


@dataclass
class TransferRouteStep:
    sender_channel_id: Optional[uuid.UUID]
    recipient_provider_acc: ProviderAccountType
    payment_type: str


@dataclass
class TransferRoute:
    first_step: TransferRouteStep
    second_step: Optional[TransferRouteStep] = None
    remittance_user_id: Optional[uuid.UUID] = None

    @property
    def estimated_fee(self) -> Decimal:
        result = self.first_step.recipient_provider_acc.provider.params.default_fee
        if self.second_step:
            result += self.second_step.recipient_provider_acc.provider.params.default_fee

        return result

    def __str__(self) -> str:
        result = f"\t1: {self.first_step.recipient_provider_acc.provider}"
        if self.second_step:
            result += f"; 2: {self.second_step.recipient_provider_acc.provider}"
        result += f"; Fee = {self.estimated_fee} USD"
        return result + "\n"

    def transfer_min_usd(self) -> Decimal:
        result = self.first_step.recipient_provider_acc.provider.params.transfer_min_usd
        if self.second_step:
            if self.second_step.recipient_provider_acc.provider.params.transfer_min_usd > result:
                result = self.second_step.recipient_provider_acc.provider.params.transfer_min_usd

        return result

    def transfer_max_usd(self) -> Decimal:
        result = self.first_step.recipient_provider_acc.provider.params.transfer_max_usd
        if self.second_step:
            if self.second_step.recipient_provider_acc.provider.params.transfer_max_usd < result:
                result = self.second_step.recipient_provider_acc.provider.params.transfer_max_usd

        return result


ONE_STEP_ROUTE_PAYMENTS = ["card"] + CRYPTO_PAYMENT_TYPES
SECOND_PAYMENT_TYPES = ["internal:bank_account"] + CRYPTO_PAYMENT_TYPES


def intersection(lst1: List[str], lst2: List[str]) -> List[str]:
    return list(set(lst1) & set(lst2))


def get_available_routes(
        recipient: Creator | PayoutChannel,
        sender_channel: PayoutChannel | None,
        cur: cursor
) -> List[TransferRoute]:
    routes: List[TransferRoute] = []
    recipient_accounts = AccountFactory.get_provider_accounts(recipient, cur)

    # One-step routes
    for provider_acc in recipient_accounts:
        for first_payment_type in intersection(ONE_STEP_ROUTE_PAYMENTS, provider_acc.supported_payment_types):
            routes.append(
                TransferRoute(
                    first_step=TransferRouteStep(
                        sender_channel_id=sender_channel.channel_id if sender_channel else None,
                        recipient_provider_acc=provider_acc,
                        payment_type=first_payment_type,
                    )
                )
            )

    if isinstance(recipient, PayoutChannel):
        return routes

    # Two-step routes (only available if first payment type is crypto)
    proxy_accounts = AccountFactory.get_proxy_provider_accounts(recipient, cur)
    for proxy_provider_acc in proxy_accounts:
        for recipient_provider_acc in recipient_accounts:
            for second_payment_type in intersection(SECOND_PAYMENT_TYPES, recipient_provider_acc.supported_payment_types):
                for first_payment_type in intersection(CRYPTO_PAYMENT_TYPES, proxy_provider_acc.supported_payment_types):
                    routes.append(
                        TransferRoute(
                            first_step=TransferRouteStep(
                                sender_channel_id=sender_channel.channel_id if sender_channel else None,
                                recipient_provider_acc=proxy_provider_acc,
                                payment_type=first_payment_type,
                            ),
                            second_step=TransferRouteStep(
                                sender_channel_id=None,
                                recipient_provider_acc=recipient_provider_acc,
                                payment_type=second_payment_type,
                            ),
                            remittance_user_id=proxy_provider_acc.payout_channel.creator_id,
                        )
                    )

    return routes


def get_cheapest_route(
        recipient: Creator | PayoutChannel,
        sender_channel: PayoutChannel | None,
        payment_type: str,
        currency_name: str | None,
        amount: Decimal | None,
        cur: cursor
) -> TransferRoute:
    available_routes = get_available_routes(recipient, sender_channel, cur)
    if not len(available_routes):
        raise APIError(
            APIError.INTERNAL,
            f"User is not ready to accept payments"
        )

    available_routes = [route for route in available_routes if route.first_step.payment_type == payment_type]
    if not len(available_routes):
        raise APIError(
            APIError.INTERNAL,
            f"Routes not found. Try to select another payment type"
        )

    if amount and currency_name:
        amount_usd = convert_currency_to_usd(amount, currency_name)
        absolute_minimum_usd = min([route.transfer_min_usd() for route in available_routes])
        if absolute_minimum_usd > amount_usd:
            min_amount_currency = convert_usd_to_currency(absolute_minimum_usd, currency_name)
            raise APIError(
                APIError.INTERNAL,
                f"The min amount for this payment route is {min_amount_currency} {currency_name}"
            )

        absolute_maximum_usd = max([route.transfer_max_usd() for route in available_routes])
        if absolute_maximum_usd < amount_usd:
            max_amount_currency = convert_usd_to_currency(absolute_maximum_usd, currency_name)
            raise APIError(
                APIError.INTERNAL,
                f"The max amount for this payment route is {max_amount_currency} {currency_name}"
            )

        available_routes = [
            route for route in available_routes
            if route.transfer_min_usd() <= amount_usd <= route.transfer_max_usd()
        ]

        if not len(available_routes):
            raise APIError(
                APIError.INTERNAL,
                f"Routes not found. Try to select another payment type"
            )

    available_routes.sort(key=lambda x: x.estimated_fee)
    # return cheapest route
    return available_routes[0]


def start_payment(
        sender: Creator | None,
        sender_channel: PayoutChannel | None,
        recipient: Creator | PayoutChannel,
        auth_account: AuthAccount | None,
        payment_type: str,
        message: str | None,
        currency_name: str | None,
        amount: Decimal | None,
        cur: cursor,
) -> PaymentIntent:
    if isinstance(recipient, PayoutChannel):
        recipient_creator = CreatorLoader.get_creator_by_id(recipient.creator_id, cur)
        if not recipient_creator:
            raise APIError(APIError.OBJECT_NOT_FOUND, "Recipient does not exist")
    else:
        recipient_creator = recipient

    route = get_cheapest_route(
        recipient=recipient,
        sender_channel=sender_channel,
        payment_type=payment_type,
        currency_name=currency_name,
        amount=amount,
        cur=cur
    )

    transfer = Transfer.create_new(
        creator_id=recipient.creator_id,
        sender=sender.creator_id if sender is not None else None,
        message=message,
        remittance_user=route.remittance_user_id,
        auth_account=auth_account,
        tm_fee=None,
        cur=cur
    )

    if not transfer:
        raise APIError(APIError.PAYMENT, "Failed to create transfer")

    payment_intent = route.first_step.recipient_provider_acc.receive_payment(
        payment_type=payment_type,
        recipient=recipient_creator,
        transfer_id=transfer.transfer_id,
        amount=amount,
        collect_fee=route.remittance_user_id is None,
        cur=cur,
    )

    transfer.create_payment(
        payment_type=payment_type,
        currency=payment_intent.currency,
        sender_channel_id=sender_channel.channel_id if sender_channel else None,
        recipient_channel_id=route.first_step.recipient_provider_acc.payout_channel.channel_id,
        provider=route.first_step.recipient_provider_acc.provider.name,
        cur=cur
    ).update(
        UpdatePaymentParams(
            status='pending',
            total_amount=amount,
            to_usd_rate=Currency.get_exchange_rate_to_usd(payment_intent.currency),
            payment_data=payment_intent.payment_data,
            external_id=payment_intent.external_id,
        ),
        cur,
    )

    if route.second_step:
        transfer.create_payment(
            payment_type=route.second_step.payment_type,
            currency=route.second_step.recipient_provider_acc.payout_channel.currency,
            sender_channel_id=route.second_step.sender_channel_id,
            recipient_channel_id=route.second_step.recipient_provider_acc.payout_channel.channel_id,
            provider=route.second_step.recipient_provider_acc.provider.name,
            cur=cur
        )

    return payment_intent


def submit_payout(
        transfer: Transfer, provider_fee1: Decimal, provider_fee2: Decimal,
        tm_fee: Decimal, amount: Decimal, external_id: str, cur: cursor,
) -> None:
    if transfer.status != 'pending payout':
        raise APIError(
            APIError.ACCESS_ERROR,
            "Transfer is not in 'pending payout' state"
        )

    second_payment = transfer.payments[1]
    creator = CreatorLoader.get_creator_by_id(transfer.creator_id, cur, with_removed=True)
    if not creator:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    recipient_provider_account = AccountFactory.get_provider_account(
        channel_id=second_payment.payout_channel_id,
        provider=second_payment.provider,
        verification_states=CreatorVerificator.get_verification_states(creator, cur),
        cur=cur,
    )

    payout_exchange_rate_to_usd = Currency.get_exchange_rate_to_usd(recipient_provider_account.payout_channel.currency)
    input_amount_usd = transfer.payments[0].total_amount * transfer.payments[0].to_usd_rate
    net_amount_usd = input_amount_usd - provider_fee1 - provider_fee2 - tm_fee
    expected_amount = net_amount_usd / payout_exchange_rate_to_usd
    if round(expected_amount, 2) != amount:
        APIError(
            APIError.PAYMENT,
            f"Amount provided not match. Expected {expected_amount} but got {amount}"
        )

    recipient_provider_account.validate_existing_transaction(amount, external_id)
    transfer.set_tm_fee(tm_fee, cur)
    transfer.payments[0].update(
        UpdatePaymentParams(provider_fee=provider_fee1), cur
    )

    second_payment.update(
        UpdatePaymentParams(
            status="submitted",
            external_id=external_id,
            provider_fee=provider_fee2,
            total_amount=amount,
            to_usd_rate=payout_exchange_rate_to_usd,
        ),
        cur
    )

    transfer.set_status('submitted', cur)


def update_payment(payment: Payment, cur: cursor, **params: Any) -> None:
    transfer = Transfer.get_by_id(payment.transfer_id, cur)
    payment.update(UpdatePaymentParams(**params), cur)
    status = params.get('status', None)
    if not status:
        raise APIError(
            APIError.PAYMENT,
            f"Unable to update payment: payment status is not set"
        )

    tm_fee = params.get('tm_fee', None)
    if tm_fee:
        transfer.set_tm_fee(tm_fee, cur)

    receiver_account = AccountFactory.get_account(payment.payout_channel_id, cur, with_removed=True)
    if receiver_account.payout_channel.creator_id == transfer.creator_id:  # payment reached receiver
        transfer.set_status(status, cur)
        if (payment.payment_type in CRYPTO_PAYMENT_TYPES and status == 'paid out'
                or payment.payment_type == 'card' and status == 'payment complete'):
            send_notification(
                transfer.creator_id,
                TransferComplete(
                    transfer_id=transfer.transfer_id,
                    total_amount=payment.total_amount,
                    currency=payment.currency,
                    message=transfer.message
                ),
                None
            )

    # payment reached payment processor
    elif receiver_account.payout_channel.creator_id == transfer.remittance_user:
        if payment.payment_index == 0:  # it is last payment in transfer
            if status in ['paid out', 'payment complete']:
                transfer.set_status("pending payout", cur)
                send_notification(
                    transfer.creator_id,
                    PayoutRequest(),
                    None
                )
            elif status == 'submitted':
                transfer.set_status('submitted', cur)
