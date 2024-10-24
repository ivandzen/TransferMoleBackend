import uuid
from fastapi import APIRouter, Depends, Form
from typing import Annotated, Dict, Any, List, Optional
from psycopg2.extensions import cursor
from pydantic import BaseModel
import logging

from ..common.api_error import APIError
from ..common.config import Config
from ..game_notifications import GameNotifications
from ..game_tasks import ReferralTaskResult
from ..notification import UserDeleted, TaskCompleted
from ..notification_utils import send_notification
from ..creator_loader import CreatorLoader
from ..authentication.auth_account import AuthAccount
from ..authentication.auth_account_factory import AuthAccountFactory
from ..payout.payout_channel import PayoutChannel
from ..payout.account_factory import AccountFactory
from .common import Context, required_access_token_ctx, database_cursor, create_or_restore_user
from ..payout.termination_account import TerminationAccount
from ..verification.creator_verificator import CreatorVerificator
from ..creator import Creator, VerificationIntent, VerificationStates
from ..crypto_network import CRYPTO_PAYMENT_TYPES
from ..payout.crypto_account import CryptoAccountDetails, CryptoPayoutChannel
from ..payout.bank_account import BankPayoutChannel
from ..payout.providers.bank_payout_provider import check_bank_account_data
from ..payment_processor import get_available_routes
from ..referrals import Referrals, ReferralCode
from ..creator_reference import CreatorReference, load_creator_by_reference

logger = logging.getLogger(__name__)
creator_router = APIRouter(prefix="/creator", tags=["creator"])


@creator_router.post("/", operation_id="register")
async def register_creator(
        context: Annotated[Context, Depends(required_access_token_ctx)],
        passphrase: Optional[str] = Form(None),
) -> None:
    if Config.CLIENT_PASS_PHRASE:
        if not passphrase or passphrase.lower() != Config.CLIENT_PASS_PHRASE.lower():
            raise APIError(APIError.WRONG_PASSPHRASE, f"Incorrect passphrase")

    if context.creator is not None:
        return None

    create_or_restore_user(context.auth_account, context.creator, context.cur)

class PayoutInfo(BaseModel):
    channels: Dict[uuid.UUID, TerminationAccount]


class CreatorInfo(BaseModel):
    creator: Creator
    payout: PayoutInfo
    auth_accounts: List[AuthAccount]
    verification_states: VerificationStates


@creator_router.get(
    path="/",
    response_model=CreatorInfo | None,
    operation_id="get_info",
)
async def get_creator_info(
        context: Annotated[Context, Depends(required_access_token_ctx)],
) -> CreatorInfo | None:
    if context.creator is None:
        return None

    termination_accounts = AccountFactory.get_creator_owned_accounts(context.creator, context.cur)
    return CreatorInfo(
        creator=context.creator,
        payout=PayoutInfo(channels=termination_accounts),
        auth_accounts=AuthAccountFactory.load_creator_accounts(context.creator.creator_id, context.cur),
        verification_states=CreatorVerificator.get_verification_states(context.creator, context.cur),
    )


class CreatorSummary(BaseModel):
    creator_id: uuid.UUID
    payment_channels: Dict[str, Dict[str, List[str | None]]]
    communication_channels: List[AuthAccount]


@creator_router.post("/summary", response_model=CreatorSummary, operation_id="get_summary")
async def get_creator_summary(
        cur: Annotated[cursor, Depends(database_cursor)],
        reference: CreatorReference
) -> CreatorSummary:
    creator = load_creator_by_reference(reference, cur)
    if not creator:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    payment_channels: Dict[str, Dict[str, List[str | None]]] = {}
    for route in get_available_routes(creator, None, cur):
        payment_type = route.first_step.payment_type
        if payment_type in CRYPTO_PAYMENT_TYPES:
            payment_type = "crypto"

        (
            payment_channels
            .setdefault(payment_type, {})
            .setdefault(
                route.first_step.recipient_provider_acc.provider.name,
                [route.first_step.recipient_provider_acc.payout_channel.currency]
            )
        )

    return CreatorSummary(
        creator_id=creator.creator_id,
        payment_channels={
            payment_type: {
                provider: [currency for currency in currencies]
                for provider, currencies in providers.items()
            }
            for payment_type, providers in payment_channels.items()
        },
        communication_channels=AuthAccountFactory.load_creator_accounts(creator.creator_id, cur)
    )


@creator_router.delete("/", operation_id="remove")
async def delete_creator(context: Annotated[Context, Depends(required_access_token_ctx)]) -> None:
    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    if context.creator.country:
        CreatorVerificator.remove_verifications(context.creator, context.cur)

    PayoutChannel.remove_all_for_creator(context.creator.creator_id, context.cur)
    context.creator.remove(context.cur)
    send_notification(context.creator.creator_id, UserDeleted(),None)


@creator_router.post("/country", operation_id="set_country")
async def set_country(
        new_country: str,
        context: Annotated[Context, Depends(required_access_token_ctx)]
) -> None:
    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    for kyc_provider, verification_state in CreatorVerificator.get_verification_states(context.creator, context.cur).root.items():
        if verification_state.name in ["verified", "verifying"]:
            raise APIError(
                APIError.CREATOR_SUBMITTED_FOR_VERIFICATION,
                "Unable to change country because creator submitted for verification"
            )

    context.creator.set_country(new_country, context.cur)


@creator_router.put("/personal_info", operation_id="update_personal_info")
async def update_personal_info(
        personal_info: Dict[str, Any],
        context: Annotated[Context, Depends(required_access_token_ctx)]
) -> None:
    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    for kyc_provider, verification_state in CreatorVerificator.get_verification_states(context.creator, context.cur).root.items():
        if verification_state.name in ["verified", "verifying"]:
            raise APIError(
                APIError.CREATOR_SUBMITTED_FOR_VERIFICATION,
                "Unable to change country because creator submitted for verification"
            )

    if not context.creator.country:
        raise APIError(APIError.INTERNAL, "Country not set for user")

    checked_data = context.creator.country.check_personal_info(personal_info)
    context.creator.update_personal_info(checked_data, context.cur)


@creator_router.post(
    path="/verify/{kyc_provider}",
    operation_id="verify",
    response_model=VerificationIntent,
)
async def verify(
        kyc_provider: str,
        context: Annotated[Context, Depends(required_access_token_ctx)]
) -> VerificationIntent | None:
    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    return CreatorVerificator.start_verification(
        context.creator, kyc_provider, context.access_token, context.cur
    )


@creator_router.post(
    path="/payout_channel/crypto",
    operation_id="create_crypto_account",
    response_model=CryptoPayoutChannel,
)
async def create_crypto_account(
        account_data: CryptoAccountDetails,
        context: Annotated[Context, Depends(required_access_token_ctx)]
) -> CryptoPayoutChannel:
    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    return AccountFactory.attach_self_custody_wallet(
        creator=context.creator,
        account_data=account_data,
        cur=context.cur,
    )


@creator_router.post(
    path="/payout_channel/bank_account",
    operation_id="create_bank_account",
    response_model=BankPayoutChannel,
)
async def create_bank_account(
        account_data: Dict[str, Any],
        context: Annotated[Context, Depends(required_access_token_ctx)]
) -> BankPayoutChannel:
    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    return AccountFactory.attach_bank_account(
        creator=context.creator,
        account_data=check_bank_account_data(context.creator, account_data),
        cur=context.cur,
    )


class AttachStripeBankAccountParams(BaseModel):
    stripe_bank_account: str


@creator_router.post(
    path="/payout_channel/stripe_bank_account",
    operation_id="attach_stripe_bank_account",
    response_model=BankPayoutChannel,
)
async def attach_stripe_bank_account(
        params: AttachStripeBankAccountParams,
        context: Annotated[Context, Depends(required_access_token_ctx)]
) -> BankPayoutChannel:
    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    return AccountFactory.attach_stripe_bank_account(
        creator=context.creator,
        stripe_bank_account_id=params.stripe_bank_account,
        cur=context.cur,
    )


@creator_router.delete("/payout_channel", operation_id="remove_payout_channel")
async def remove_payout_channel(
        channel_id: uuid.UUID,
        context: Annotated[Context, Depends(required_access_token_ctx)]
) -> None:
    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    account_info = AccountFactory.get_account(channel_id, context.cur)
    if account_info.payout_channel.creator_id != context.creator.creator_id:
        raise APIError(
            APIError.ACCESS_ERROR,
            f"You have no rights to edit this channel"
        )

    account_info.remove(context.cur)


@creator_router.get(
    path="/referral_code",
    operation_id="get_referral_code",
)
async def get_referral_code(context: Annotated[Context, Depends(required_access_token_ctx)]) -> ReferralCode:
    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    result = Referrals.get_referral_code(creator_id=context.creator.creator_id, cur=context.cur)
    return result


def notify_referral(referral_id: uuid.UUID, referree_id: uuid.UUID) -> None:
    async def on_complete(referral_dialogs: List[AuthAccount], cur: cursor) -> None:
        referral = CreatorLoader.get_creator_by_id(referral_id, cur)
        referree_dialogs = AuthAccountFactory.load_creator_accounts(referree_id, cur)
        for referral_dialog in referral_dialogs:
            if referral_dialog.platform != "tg":
                continue

            for referree_dialog in referree_dialogs:
                if referree_dialog.platform != "tg":
                    continue

                GameNotifications.new_referree(referral_id if referral else None, referree_id, cur)
                await referree_dialog.send_referree_notification()
                if referral:
                    await referral_dialog.send_referral_notification()

                return

    send_notification(
        referral_id,
        TaskCompleted(
            subcategory='referral_program',
            task_result=ReferralTaskResult(referree=referree_id),
        ),
        on_complete,
    )


@creator_router.post(
    path="/referral_code",
    operation_id="apply_referral_code",
)
async def apply_referral_code(
        referral_code: Annotated[str, Form()],
        context: Annotated[Context, Depends(required_access_token_ctx)]
) -> None:
    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    referral_id = Referrals.apply_referral_code(creator_id=context.creator.creator_id, referral_code=referral_code, cur=context.cur)
    notify_referral(referral_id=referral_id, referree_id=context.creator.creator_id)


@creator_router.post(
    path="/referral_summary/{referral_code}",
    response_model=CreatorSummary,
    operation_id="get_referral_summary"
)
async def get_referral_summary(
        referral_code: str,
        cur: Annotated[cursor, Depends(database_cursor)],
) -> CreatorSummary:
    referral_id, _ = Referrals.get_referral_id(referral_code, cur)
    creator = CreatorLoader.get_creator_by_id(referral_id, cur, with_removed=True)
    if creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    payment_channels: Dict[str, Dict[str, List[str | None]]] = {}
    for route in get_available_routes(creator, None, cur):
        payment_type = route.first_step.payment_type
        if payment_type in CRYPTO_PAYMENT_TYPES:
            payment_type = "crypto"

        (
            payment_channels
            .setdefault(payment_type, {})
            .setdefault(
                route.first_step.recipient_provider_acc.provider.name,
                [route.first_step.recipient_provider_acc.payout_channel.currency]
            )
        )

    return CreatorSummary(
        creator_id=creator.creator_id,
        payment_channels={
            payment_type: {
                provider: [currency for currency in currencies]
                for provider, currencies in providers.items()
            }
            for payment_type, providers in payment_channels.items()
        },
        communication_channels=AuthAccountFactory.load_creator_accounts(creator.creator_id, cur)
    )
