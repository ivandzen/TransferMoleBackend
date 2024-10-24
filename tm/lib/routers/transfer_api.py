import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Annotated, List, Literal, Optional, Tuple
from psycopg2.extensions import cursor
from decimal import Decimal

from ..transfer import Transfer
from .common import Context, OptionalContext, required_access_token_ctx, optional_access_token_ctx, database_cursor, Duration
from ..creator import Creator
from ..common.api_error import APIError
from ..creator_loader import CreatorLoader
from ..authentication.auth_account_factory import AuthAccountFactory, AuthAccount
from ..authentication.auth_account import SocialReference
from ..payment_processor import start_payment, update_payment, submit_payout
from ..currency import Currency
from ..payment import Payment
from ..crypto_network import CryptoNetworks
from ..payout.bank_account import BankPayoutChannel
from ..payout.crypto_account import CryptoPayoutChannel
from ..payout.account_factory import AccountFactory
from ..payout.payment_intent import PaymentIntent
from ..payout.termination_account import TerminationAccount
from ..crypto_network import CRYPTO_NETWORK_NAMES
from ..creator_reference import CreatorReference, load_creator_by_reference
from ..verification.creator_verificator import CreatorVerificator

logger = logging.getLogger(__name__)
transfer_router = APIRouter(prefix="/transfer", tags=["transfer"])


class GetTransfersParameters(BaseModel):
    from_time: Optional[int] = None
    duration: Optional[Duration] = None
    exclude_statuses: Optional[List[
        Annotated[str, Literal["created", "pending payout", "canceled", "expired"]]
    ]] = None


@transfer_router.post(
    path="/list",
    response_model=List[Transfer],
    operation_id="list"
)
async def get_transfers(
        context: Annotated[Context, Depends(required_access_token_ctx)],
        params: GetTransfersParameters | None = None,
) -> List[Transfer]:
    from_time = datetime.fromtimestamp(params.from_time) if params and params.from_time else None
    duration = params.duration.to_timedelta() if params and params.duration else None
    creator_id = context.creator.creator_id if context.auth_account.platform != "admin" and context.creator else None
    remittance_user = context.creator.creator_id if context.auth_account.platform == "admin" and context.creator else None
    result: List[Transfer] = []

    for _, transfer in Transfer.get_transfers(
            creator_id=creator_id,
            remittance_user=remittance_user,
            from_time=from_time,
            duration=duration,
            exclude_statuses=params.exclude_statuses if params and params.exclude_statuses else [],
            cur=context.cur,
    ).items():
        if context.auth_account.platform == "admin":
            # User has no right to read attached message
            transfer.message = None
        result.append(transfer)

    return result


@transfer_router.get(
    path="/{transfer_id}",
    response_model=Transfer,
    operation_id="get"
)
async def get_transfer(
        transfer_id: uuid.UUID,
        context: Annotated[OptionalContext, Depends(optional_access_token_ctx)]
) -> Transfer:
    transfer = Transfer.get_by_id(transfer_id, context.cur)
    if not context.access_token or context.creator and transfer.creator_id != context.creator.creator_id:
        # User has no right to read attached message
        transfer.message = None

    return transfer


def get_creator_auth_acc_target_acc(
        recipient: CreatorReference,
        cur: cursor,
) -> Tuple[Creator, AuthAccount | None]:
    creator = load_creator_by_reference(recipient, cur)
    if not creator:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    auth_account = None
    if recipient.social:
        if recipient.social.username:
            auth_account = AuthAccountFactory.get_by_username(
                recipient.social.platform, recipient.social.username, cur
            )
        elif recipient.social.userid:
            auth_account = AuthAccountFactory.get_by_userid(
                recipient.social.platform, recipient.social.userid, cur
            )
        else:
            raise APIError(APIError.INTERNAL, "Invalid social ref. Either username or userid must be specified")
    else:
        auth_accounts = AuthAccountFactory.load_creator_accounts(
            creator.creator_id, cur
        )
        if len(auth_accounts):
            auth_account = auth_accounts[0]

    return creator, auth_account


MESSAGE_RE = "^[^\\'\";]{0,50}$"


class BeginCryptoTransferParams(BaseModel):
    recipient: CreatorReference
    network: CRYPTO_NETWORK_NAMES
    currency: str
    amount: Decimal
    message: Optional[str] = Field(default=None, pattern=MESSAGE_RE)


@transfer_router.post(
    path="/begin/crypto",
    response_model=PaymentIntent,
    operation_id="begin_crypto"
)
async def begin_crypto_transfer(
        cur: Annotated[cursor, Depends(database_cursor)],
        params: BeginCryptoTransferParams,
) -> PaymentIntent:
    creator, auth_account = get_creator_auth_acc_target_acc(
        recipient=params.recipient,
        cur=cur
    )
    return start_payment(
        sender=CreatorLoader.get_stranger(cur),
        sender_channel=None,
        recipient=creator,
        auth_account=auth_account,
        payment_type=f"crypto:{params.network}",
        message=params.message,
        currency_name=params.currency,
        amount=params.amount,
        cur=cur,
    )


class BeginCardTransferParams(BaseModel):
    recipient: CreatorReference
    message: Optional[str] = Field(default=None, pattern=MESSAGE_RE)


@transfer_router.post(
    path="/begin/card",
    response_model=PaymentIntent,
    operation_id="begin_card"
)
async def begin_card_transfer(
        cur: Annotated[cursor, Depends(database_cursor)],
        params: BeginCardTransferParams,
) -> PaymentIntent:
    creator, auth_account = get_creator_auth_acc_target_acc(
        recipient=params.recipient,
        cur=cur
    )
    return start_payment(
        sender=CreatorLoader.get_stranger(cur),
        sender_channel=None,
        recipient=creator,
        auth_account=auth_account,
        payment_type="card",
        message=params.message,
        currency_name=None,
        amount=None,
        cur=cur,
    )


class TransferSubmitCryptoParams(BaseModel):
    transaction_id: str


@transfer_router.post(
    path="/{transfer_id}/submit/crypto",
    operation_id="submit_crypto_transaction"
)
async def transfer_submit_crypto(
        transfer_id: uuid.UUID,
        params: TransferSubmitCryptoParams,
        cur: Annotated[cursor, Depends(database_cursor)]
) -> None:
    payment = Payment.load(transfer_id, payment_index=0, cur=cur)
    if not payment.total_amount:
        raise APIError(APIError.PAYMENT, f"Payment amount not specified - submit is not available")

    if payment.external_id is not None or payment.status == 'paid out':
        raise APIError(APIError.PAYMENT, f"Payment already submitted")

    crypto_channel = AccountFactory.get_crypto_payout_channel(payment.payout_channel_id, cur, True)
    network = CryptoNetworks.get(crypto_channel.data.network)
    network.check_transaction(
        params.transaction_id,
        crypto_channel.data.address,
        payment.currency,
        payment.total_amount
    )

    update_payment(
        payment=payment, cur=cur, external_id=params.transaction_id, status="submitted"
    )


class AdminPayoutDetails(BaseModel):
    payment: Payment
    recipient_channel: BankPayoutChannel | CryptoPayoutChannel
    to_usd_rate: Decimal
    social_ref: Optional[SocialReference] = None
    first_provider: str
    first_provider_fee: Decimal
    second_provider: str
    second_provider_fee: Decimal


@transfer_router.post(
    path="/{transfer_id}/payout/prepare",
    operation_id="prepare_payout",
    response_model=AdminPayoutDetails
)
async def admin_prepare_payout_details(
        transfer_id: uuid.UUID,
        context: Annotated[Context, Depends(required_access_token_ctx)]
) -> AdminPayoutDetails:
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    transfer = Transfer.get_by_id(transfer_id, context.cur)
    if not context.creator or transfer.remittance_user != context.creator.creator_id:
        raise APIError(
            APIError.ACCESS_ERROR,
            "You dont have permissions to access payout channels of this transfer"
        )

    if transfer.status != 'pending payout':
        raise APIError(
            APIError.ACCESS_ERROR,
            "Transfer is not in 'pending payout' state"
        )

    creator = CreatorLoader.get_creator_by_id(transfer.creator_id, context.cur, with_removed=True)
    if creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    proxy_provider_account = AccountFactory.get_provider_account(
        channel_id=transfer.payments[0].payout_channel_id,
        provider=transfer.payments[0].provider,
        verification_states=CreatorVerificator.get_verification_states(creator, context.cur),
        cur=context.cur
    )

    recipient_provider_account = AccountFactory.get_provider_account(
        channel_id=transfer.payments[1].payout_channel_id,
        provider=transfer.payments[1].provider,
        verification_states=CreatorVerificator.get_verification_states(creator, context.cur),
        cur=context.cur
    )

    return AdminPayoutDetails(
        payment=transfer.payments[0],
        recipient_channel=recipient_provider_account.payout_channel,
        to_usd_rate=Currency.get_exchange_rate_to_usd(recipient_provider_account.payout_channel.currency),
        social_ref=SocialReference(
            platform=transfer.auth_account.platform,
            username=transfer.auth_account.username
        ) if transfer.auth_account else None,
        first_provider=proxy_provider_account.provider.name,
        first_provider_fee=proxy_provider_account.provider.params.default_fee,
        second_provider=recipient_provider_account.provider.name,
        second_provider_fee=recipient_provider_account.provider.params.default_fee,
    )


class SubmitPayoutParams(BaseModel):
    provider_fee1: str
    provider_fee2: str
    tm_fee: str
    amount: str
    external_id: str


@transfer_router.post(
    path="/{transfer_id}/payout/submit",
    operation_id="submit_payout"
)
async def admin_submit_payout(
        transfer_id: uuid.UUID,
        context: Annotated[Context, Depends(required_access_token_ctx)],
        params: SubmitPayoutParams,
) -> None:
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    transfer = Transfer.get_by_id(transfer_id, context.cur)
    if not context.creator or transfer.remittance_user != context.creator.creator_id:
        raise APIError(
            APIError.ACCESS_ERROR,
            "You are not intermediate of this transfer"
        )

    submit_payout(
        transfer, Decimal(params.provider_fee1), Decimal(params.provider_fee2),
        Decimal(params.tm_fee), Decimal(params.amount), params.external_id, context.cur
    )
    logger.info(f"Admin user {context.auth_account.username} made payout for transfer {transfer_id}")


@transfer_router.post(
    path="/{transfer_id}/payout/cancel",
    operation_id="cancel_payout"
)
async def admin_cancel_payout(
        transfer_id: uuid.UUID,
        context: Annotated[Context, Depends(required_access_token_ctx)],
) -> None:
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    transfer = Transfer.get_by_id(transfer_id, context.cur)
    if transfer.status == 'pending payout':
        transfer.set_status('canceled', context.cur)
    else:
        raise APIError(APIError.INTERNAL, "Transfer is not in pending payout state")


@transfer_router.post(
    path="/{transfer_id}/payout_channel/{payment_index}",
    operation_id="get_payout_channel",
    response_model=TerminationAccount,
)
def admin_get_transfer_payout_channel(
        transfer_id: uuid.UUID,
        payment_index: int,
        context: Annotated[Context, Depends(required_access_token_ctx)],
) -> TerminationAccount:
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    transfer = Transfer.get_by_id(transfer_id, context.cur)
    if not context.creator or transfer.remittance_user != context.creator.creator_id:
        raise APIError(
            APIError.ACCESS_ERROR,
            "You dont have permissions to access payout channels of this transfer"
        )

    if payment_index >= len(transfer.payments):
        raise APIError(APIError.WRONG_PARAMETERS, f"payment_index out of range")

    payment = transfer.payments[payment_index]
    return AccountFactory.get_account(payment.payout_channel_id, context.cur, with_removed=True)
