import datetime
import logging
import uuid
from decimal import Decimal

from cryptography.hazmat.primitives.asymmetric.dsa import DSAPublicKey
from fastapi import APIRouter, Request, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator
from typing import Dict, Annotated, ClassVar, Optional, List, Literal, Any
import requests
from base64 import b64decode
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from psycopg2.extensions import cursor

from ..common.api_error import APIError
from ..common.config import Config
from ..common.database import Database
from ..circle import circle_get_user_token, circle_get_wallet, get_transfermole_network, circle_get_token_details
from ..creator_loader import CreatorLoader
from ..payout.account_factory import AccountFactory
from ..payout.crypto_account import CryptoAccountDetails
from ..payment import Payment
from ..payment_processor import update_payment
from ..currency import Currency
from ..payout.providers.payout_provider_cache import PROVIDER_CIRCLE
from ..transfer import Transfer


logger = logging.getLogger(__name__)
router = APIRouter(prefix=f"/circle", tags=["circle_webhook"])


class TransferNotification(BaseModel):
    id: uuid.UUID
    blockchain: str
    walletId: uuid.UUID
    tokenId: uuid.UUID
    userId: uuid.UUID
    destinationAddress: str
    amounts: List[Decimal]
    nftTokenIds: List[str]
    refId: Optional[uuid.UUID] = None
    state: Literal['CONFIRMED', 'COMPLETE']
    errorReason: Optional[str] = None
    transactionType: Literal['INBOUND', 'OUTBOUND']
    txHash: Optional[str] = None
    createDate: datetime.datetime
    updateDate: datetime.datetime
    errorDetails: Optional[Any] = None


class Notification(BaseModel):
    subscriptionId: uuid.UUID
    notificationId: uuid.UUID
    notificationType: str
    notification: Dict
    timestamp: datetime.datetime
    version: int


class CirclePublicKeyData(BaseModel):
    id: uuid.UUID
    algorithm: str
    publicKey: bytes
    createDate: datetime.datetime

    @field_validator("publicKey", mode="before")
    @classmethod
    def public_key_validator(cls, value: str) -> bytes:
        return b64decode(value)


class CirclePublicKey(BaseModel):
    data: CirclePublicKeyData

    def check(self, message: bytes, signature: str) -> None:
        sig_bytes = b64decode(signature)
        match self.data.algorithm:
            case "ECDSA_SHA_256":
                public_key = serialization.load_der_public_key(self.data.publicKey)
                if not isinstance(public_key, DSAPublicKey):
                    raise APIError(APIError.INTERNAL, "Wrong public key")

                public_key.verify(sig_bytes, message, ec.ECDSA(hashes.SHA256()).algorithm)
            case unknown:
                logger.warning(f"Algorithm {unknown} is not implemented")
                raise HTTPException(status_code=500, detail="Unable to check notification signature")


class CirclePublicKeys:
    KEY_CACHE: ClassVar[Dict[str, CirclePublicKey]] = {}
    session: ClassVar[requests.Session] = requests.Session()

    @staticmethod
    def get_public_key(key_id: str) -> CirclePublicKey:
        key = CirclePublicKeys.KEY_CACHE.get(key_id, None)
        if key:
            return key

        response = CirclePublicKeys.session.get(
            url=f"https://api.circle.com/v2/notifications/publicKey/{key_id}",
            headers={
                "Authorization": f"Bearer {Config.CIRCLE_API_KEY}",
            }
        )

        try:
            key = CirclePublicKey.model_validate(response.json())
            CirclePublicKeys.KEY_CACHE[key_id] = key
            return key
        except Exception as e:
            logger.warning(f"Failed to retrieve public key {key_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve public key")


async def get_notification(request: Request) -> Notification:
    key_id = request.headers.get("X-Circle-Key-Id")
    if key_id is None:
        raise HTTPException(status_code=403, detail=f"Key header not found")

    key = CirclePublicKeys.get_public_key(key_id)
    signature = request.headers.get("X-Circle-Signature")
    if not signature:
        raise HTTPException(status_code=403, detail=f"Signature header not set")

    try:
        key.check(await request.body(), signature)
        return Notification.model_validate(await request.json())
    except Exception as e:
        logger.warning(f"Failed to parse notification object: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse notification object")


def process_webhook_test(notification: Notification) -> None:
    logger.info(f"Test notification received: {notification}")


def process_wallet_created(notification: Notification, cur: cursor) -> None:
    user_id = notification.notification.get("userId", None)
    if not user_id:
        return

    wallet_ids = notification.notification.get("correlationIds", [])
    if not len(wallet_ids):
        return

    if notification.notification.get("type", None) not in ["CREATE_WALLET", "INITIALIZE"]:
        return

    if notification.notification.get("status", None) != "COMPLETE":
        return

    user_token = circle_get_user_token(user_id)
    wallet = circle_get_wallet(user_token.data.userToken, uuid.UUID(wallet_ids[0]))
    creator = CreatorLoader.get_creator_by_id(uuid.UUID(user_id), cur)
    if creator is None:
        raise APIError(APIError.INTERNAL, "User not found")

    AccountFactory.attach_circle_crypto_account(
        creator=creator,
        account_data=CryptoAccountDetails(
            network=get_transfermole_network(wallet.data.wallet.blockchain),
            address=wallet.data.wallet.address,
            currency="USDC",
        ),
        external_id=str(wallet.data.wallet.id),
        cur=cur
    )


def process_inbound_transaction(notification: Notification, cur: cursor) -> None:
    tfer_notification = TransferNotification.model_validate(notification.notification)
    if tfer_notification.transactionType != 'INBOUND':
        raise APIError(APIError.INTERNAL, "transactions.outbound type is not INBOUND")

    if tfer_notification.refId:
        # Transactions with refId were send from TransferMole - process in outbound path
        pass

    if tfer_notification.state != 'COMPLETE':
        return

    circle_account = AccountFactory.get_circle_account(external_id=str(tfer_notification.walletId), cur=cur)
    transfer = Transfer.create_new(
        creator_id=circle_account.payout_channel.creator_id,
        sender=None,
        message=None,
        remittance_user=None,
        auth_account=None,
        tm_fee=None,
        cur=cur
    )

    if not transfer:
        raise APIError(APIError.INTERNAL, "Failed to create new transfer")

    token = circle_get_token_details(tfer_notification.tokenId)
    payment = transfer.create_payment(
        payment_type=f"crypto:{circle_account.payout_channel.data.network}",
        currency=token.data.token.symbol,
        sender_channel_id=None,
        recipient_channel_id=circle_account.payout_channel.channel_id,
        provider=PROVIDER_CIRCLE.name,
        cur=cur
    )

    update_payment(
        payment, cur,
        total_amount=tfer_notification.amounts[0],
        to_usd_rate=Currency.get_exchange_rate_to_usd(token.data.token.symbol),
        external_id=tfer_notification.txHash,
        status='paid out',
        tm_fee=None,
    )


def process_outbound_transaction(notification: Notification, cur: cursor) -> None:
    tfer_notification = TransferNotification.model_validate(notification.notification)
    if tfer_notification.transactionType != 'OUTBOUND':
        raise APIError(APIError.INTERNAL, "transactions.outbound type is not OUTBOUND")

    if not tfer_notification.refId:
        raise APIError(APIError.INTERNAL, "refId is not set for outbound transaction")

    if tfer_notification.state != 'COMPLETE':
        return

    token = circle_get_token_details(tfer_notification.tokenId)
    payment = Payment.load(tfer_notification.refId, 0, cur)
    update_payment(
        payment, cur,
        total_amount=tfer_notification.amounts[0],
        to_usd_rate=Currency.get_exchange_rate_to_usd(token.data.token.symbol),
        external_id=tfer_notification.txHash,
        status='paid out',
        tm_fee=None,
    )


@router.get(path="")
async def get_webhook(notification: Annotated[Notification, Depends(get_notification)]) -> Response:
    return Response(status_code=200)


@router.post(path="")
async def post_webhook(notification: Annotated[Notification, Depends(get_notification)]) -> Response:
    cur = Database.begin()
    logger.info(f"Notification: {notification}")
    try:
        match notification.notificationType:
            case "webhooks.test":
                process_webhook_test(notification)
            case "challenges.createWallet" | "challenges.initialize":
                process_wallet_created(notification, cur)
            case "transactions.inbound":
                process_inbound_transaction(notification, cur)
            case "transactions.outbound":
                process_outbound_transaction(notification, cur)
        Database.commit()
    except Exception as e:
        logger.warning(f"Failed to process notification {notification}: {e}")
        Database.rollback()

    return Response(status_code=200)
