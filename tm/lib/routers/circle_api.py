import logging
import uuid
from decimal import Decimal
from psycopg2.extensions import cursor
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Annotated, Optional, Literal

from ..payment_processor import start_payment
from .transfer_api import BeginCryptoTransferParams, get_creator_auth_acc_target_acc
from .common import Context, required_access_token_ctx
from ..common.api_error import APIError
from ..payout.account_factory import AccountFactory
from ..payout.providers.payout_provider_cache import PROVIDER_CIRCLE
from ..crypto_network import CryptoNetworks, CRYPTO_NETWORK_NAMES
from ..payout.crypto_account import CryptoAccountDetails
from ..creator import Creator
from ..creator_loader import CreatorLoader
from ..authentication.auth_account import AuthAccount
from ..payout.payout_channel import PayoutChannel
from ..circle import (circle_get_user_status, circle_get_wallets, get_transfermole_network,
                      circle_create_wallet, circle_user_initialize, circle_estimate_transfer_fee,
                      circle_get_wallet, circle_get_wallet_balances, circle_initiate_transfer, CircleWalletData,
                      circle_restore_pin, circle_get_user, circle_get_user_token, circle_create_user)
from ..verification.creator_verificator import CreatorVerificator

logger = logging.getLogger(__name__)
circle_router = APIRouter(prefix="/circle", tags=["circle"])


class ChallengeResponse(BaseModel):
    userToken: str
    encryptionKey: str
    challengeId: Optional[str] = None


@circle_router.post(
    path="/init_wallet/{network}",
    response_model=ChallengeResponse,
    operation_id="circle_wallet_init",
)
async def circle_wallet_init(
        network: str,
        context: Annotated[Context, Depends(required_access_token_ctx)],
) -> ChallengeResponse:
    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    if not context.creator.country:
        raise APIError(APIError.INTERNAL, "Country not set for user")

    circle_user = circle_get_user(context.creator.creator_id)
    if not circle_user:
        circle_create_user(context.creator.creator_id)
        circle_user = circle_get_user(context.creator.creator_id)

    user_token = circle_get_user_token(context.creator.creator_id)
    if circle_user.pinStatus == "ENABLED":
        wallets = circle_get_wallets(context.creator.creator_id)
        existing_wallet: CircleWalletData | None = None
        for wallet in wallets.data.wallets:
            if get_transfermole_network(wallet.blockchain) == network:
                existing_wallet = wallet
                break

        if not existing_wallet:
            challenge_id = circle_create_wallet(user_token.data.userToken, network)
        else:
            challenge_id = None
            AccountFactory.attach_circle_crypto_account(
                context.creator,
                CryptoAccountDetails(network=network, address=existing_wallet.address, currency="USDC"),
                external_id=str(existing_wallet.id),
                cur=context.cur,
            )
    else:
        challenge_id = circle_user_initialize(user_token.data.userToken, network)

    return ChallengeResponse(
        userToken=user_token.data.userToken,
        encryptionKey=user_token.data.encryptionKey,
        challengeId=challenge_id,
    )


class CircleStartTransferResult(ChallengeResponse):
    transfer_id: uuid.UUID


def start_transfer_internal(
        sender: Creator,
        source_payout_channel: uuid.UUID,
        recipient: Creator | PayoutChannel,
        recipient_auth_account: AuthAccount | None,
        network_name: CRYPTO_NETWORK_NAMES,
        currency_name: str,
        amount: Decimal,
        message: str | None,
        gas_limits: Literal["low", "medium", "high"],
        cur: cursor,
) -> CircleStartTransferResult:
    source_channel = AccountFactory.get_provider_account(
        channel_id=source_payout_channel,
        provider=PROVIDER_CIRCLE.name,
        cur=cur,
        verification_states=CreatorVerificator.get_verification_states(sender, cur),
    )

    payment_intent = start_payment(
        sender=sender,
        sender_channel=source_channel.payout_channel,
        recipient=recipient,
        auth_account=recipient_auth_account,
        payment_type=f"crypto:{network_name}",
        message=message,
        currency_name=currency_name,
        amount=amount,
        cur=cur,
    )

    if not payment_intent.payment_data or not payment_intent.payment_data.destination_crypto_address:
        logger.error(f"Payment intent has no payment_data.destination_crypto_address field")
        raise APIError(
            APIError.INTERNAL,
            f"Unexpected error. Please, contact customer support"
        )

    wallets = circle_get_wallets(sender.creator_id)
    if len(wallets.data.wallets) == 0:
        raise APIError(
            APIError.INTERNAL,
            "User don't have Circle wallets"
        )

    circle_user = circle_get_user(sender.creator_id)
    if circle_user.pinStatus != "ENABLED":
        raise APIError(
            APIError.INTERNAL,
            f"You should complete user initialization before sending transactions"
        )

    user_token = circle_get_user_token(sender.creator_id)
    wallet = circle_get_wallet(
        user_token=user_token.data.userToken,
        wallet_id=wallets.data.wallets[0].id
    )

    source_address = source_channel.payout_channel.data.address
    if wallet.data.wallet.address.lower() != source_address:
        logger.error(
            f"Default crypto account address "
            f"of the user {sender.creator_id} mismatch Circle wallet address.\n"
            f"Circle wallet address: {wallet.data.wallet.address.lower()}\n"
            f"Default crypto account address: {source_address}\n"
        )
        raise APIError(
            APIError.INTERNAL,
            "Unexpected error. Please, contact customer support"
        )

    network = CryptoNetworks.get(network_name)
    token = network.currencies.get(currency_name, None)
    if token is None:
        raise APIError(
            APIError.INTERNAL,
            f"Network {network_name} "
            f"is not supporting {currency_name}"
        )

    if wallets.data.wallets[0].state != "LIVE":
        raise APIError(
            APIError.INTERNAL,
            f"Circle wallet {wallets.data.wallets[0].id} is not LIVE"
        )

    wallet_balances = circle_get_wallet_balances(
        wallet_id=wallets.data.wallets[0].id,
        token_address=token.contract_address
    )

    if len(wallet_balances.data.tokenBalances) == 0:
        raise APIError(
            APIError.INTERNAL,
            f"User has no {currency_name} "
            f"on {network_name}"
        )

    gas_estimation_result = circle_estimate_transfer_fee(
        source=wallet.data.wallet.address,
        destination=payment_intent.payment_data.destination_crypto_address,
        amount=amount,
        token=wallet_balances.data.tokenBalances[0].token,
    ).data

    match gas_limits:
        case "low":
            gas_params = gas_estimation_result.low
        case "medium":
            gas_params = gas_estimation_result.medium
        case "high":
            gas_params = gas_estimation_result.high

        case unknown:
            raise APIError(
                APIError.INTERNAL,
                f"Unsupported gas limits {unknown}"
            )

    return CircleStartTransferResult(
        transfer_id=payment_intent.transfer_id,
        userToken=user_token.data.userToken,
        encryptionKey=user_token.data.encryptionKey,
        challengeId=circle_initiate_transfer(
            user_token=user_token.data.userToken,
            source_wallet_id=wallet.data.wallet.id,
            destination=payment_intent.payment_data.destination_crypto_address,
            amount=amount,
            token=wallet_balances.data.tokenBalances[0].token,
            gas_params=gas_params,
            transfer_id=payment_intent.transfer_id,
        )
    )


class CircleStartTransferParams(BeginCryptoTransferParams):
    source_payout_channel: uuid.UUID
    gas_limits: Literal["low", "medium", "high"]


@circle_router.post(
    path="/transfer/start",
    operation_id="start_transfer",
    response_model=CircleStartTransferResult,
)
async def start_transfer(
        params: CircleStartTransferParams,
        context: Annotated[Context, Depends(required_access_token_ctx)],
) -> CircleStartTransferResult:
    recipient, auth_account = get_creator_auth_acc_target_acc(
        recipient=params.recipient,
        cur=context.cur
    )

    if not context.creator:
        raise APIError(APIError.OBJECT_NOT_FOUND, "You are not registered")

    return start_transfer_internal(
        sender=context.creator,
        source_payout_channel=params.source_payout_channel,
        recipient=recipient,
        recipient_auth_account=auth_account,
        network_name=params.network,
        currency_name=params.currency,
        amount=params.amount,
        message=params.message,
        gas_limits=params.gas_limits,
        cur=context.cur
    )


class CircleStartArbitraryTransferParams(BaseModel):
    network: CRYPTO_NETWORK_NAMES
    address: str
    currency: str
    amount: Decimal
    source_payout_channel: uuid.UUID
    gas_limits: Literal["low", "medium", "high"]


@circle_router.post(
    path="/transfer/start_arbitrary",
    operation_id="start_arbitrary_transfer",
    response_model=CircleStartTransferResult,
)
async def start_arbitrary_transfer(
        params: CircleStartArbitraryTransferParams,
        context: Annotated[Context, Depends(required_access_token_ctx)],
) -> CircleStartTransferResult:
    if params.network != "Polygon":
        raise APIError(APIError.INTERNAL, "Only Polygon is supported currently")

    if not context.creator:
        raise APIError(APIError.OBJECT_NOT_FOUND, "You are not registered")

    recipient_channel = AccountFactory.attach_self_custody_wallet(
        CreatorLoader.get_stranger(context.cur),
        CryptoAccountDetails(
            network=params.network,
            address=params.address,
            currency=params.currency,
        ),
        cur=context.cur
    )

    return start_transfer_internal(
        sender=context.creator,
        source_payout_channel=params.source_payout_channel,
        recipient=recipient_channel,
        recipient_auth_account=None,
        network_name=params.network,
        currency_name=params.currency,
        amount=params.amount,
        message=None,
        gas_limits=params.gas_limits,
        cur=context.cur
    )


@circle_router.post(
    path="/restore_pin",
    operation_id="restore_pin",
    response_model=ChallengeResponse | None,
)
async def restore_pin(
        context: Annotated[Context, Depends(required_access_token_ctx)],
) -> ChallengeResponse | None:
    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    user_token = circle_get_user_token(context.creator.creator_id)
    user_status = circle_get_user_status(user_token.data.userToken)
    if user_status.data.pinStatus == "ENABLED":
        return ChallengeResponse(
            userToken = user_token.data.userToken,
            encryptionKey = user_token.data.encryptionKey,
            challengeId = circle_restore_pin(user_token.data.userToken),
        )

    return None
