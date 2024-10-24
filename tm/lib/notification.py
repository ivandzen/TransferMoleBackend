from datetime import datetime
from pydantic import BaseModel, Field, RootModel
from typing import Literal, List, Union, Optional, Any
import uuid
from decimal import Decimal
import logging

from .common.config import Config
from .authentication.auth_account import AuthAccount, get_platform_name

logger = logging.getLogger(__name__)

EventCategory = Literal[
    'registration complete',
    'user restored',
    'account created',
    'account deleted',
    'user deleted',
    'payout request',
    'verification started',
    'verification complete',
    'payment complete',
    'user referred',
    'task completed',
]

class BaseNotification(BaseModel):
    category: EventCategory
    subcategory: Optional[str]

    def user_message(self, _auth_acc: AuthAccount) -> str | None:
        return None

    def admin_message(self, _auth_acc: AuthAccount) -> str | None:
        return None

    async def send(self, auth_accounts: List[AuthAccount]) -> None:
        if Config.DISABLE_NOTIFICATIONS:
            return

        for dialog in auth_accounts:
            message = self.user_message(dialog)
            admin_message = self.admin_message(dialog)
            if message or admin_message:
                await dialog.send_message(
                    message=message,
                    admin_message=admin_message,
                    category=self.category,
                )


class UserRestoredOrRegistered(BaseNotification):
    subcategory: Optional[str] = Field(None)

    def user_message(self, auth_acc: AuthAccount) -> str | None:
        prefix = "@" if auth_acc.platform in ["ig", "tw", "tg"] else ""
        message = (f"🥳 Thank you, {prefix}{auth_acc.username} for registering with TransferMole. You can now "
                   f"receive crypto + cash payments with your {get_platform_name(auth_acc.platform)} username "
                   f"- nothing else required!\n")
        if auth_acc.platform in ["ig", "wa"]:
            message += f"Just type 'menu' here to see main menu."

        return message


class UserRegistered(UserRestoredOrRegistered):
    category: Literal['registration complete'] = Field('registration complete')


class UserRestored(UserRestoredOrRegistered):
    category: Literal['user restored'] = Field('user restored')


class AccountCreated(BaseNotification):
    category: Literal['account created'] = Field('account created')
    subcategory: Optional[str] = Field(None)
    channel_id: uuid.UUID
    type: str


class AccountDeleted(BaseNotification):
    category: Literal['account deleted'] = Field('account deleted')
    subcategory: Optional[str] = Field(None)
    channel_id: uuid.UUID
    type: str


class UserDeleted(BaseNotification):
    category: Literal['user deleted'] = Field('user deleted')
    subcategory: Optional[str] = Field(None)

    def user_message(self, auth_acc: AuthAccount) -> str | None:
        prefix = "@" if auth_acc.platform in ["ig", "tw", "tg"] else ""
        return f"{prefix}{auth_acc.username} your account was deleted"


class PayoutRequest(BaseNotification):
    category: Literal['payout request'] = Field('payout request')
    subcategory: Optional[str] = Field(None)

    def admin_message(self, auth_acc: AuthAccount) -> str | None:
        return f"User {auth_acc.username} ({auth_acc.platform}) is awaiting payout"


class VerificationStarted(BaseNotification):
    category: Literal['verification started'] = Field('verification started')
    subcategory: Optional[str] = Field(None)
    verification_provider: str

    def user_message(self, auth_acc: AuthAccount) -> str | None:
        prefix = "@" if auth_acc.platform in ["ig", "tw", "tg"] else ""
        return f"Thank you, {prefix}{auth_acc.username}, your account was submitted for verification."

    def admin_message(self, auth_acc: AuthAccount) -> str | None:
        return (
            None if self.verification_provider != "Internal"
            else f"User {auth_acc.username} ({auth_acc.platform}) submitted KYC information"
        )


class VerificationComplete(BaseNotification):
    category: Literal['verification complete'] = Field('verification complete')
    subcategory: Optional[str] = Field(None)
    verification_provider: str

    def user_message(self, auth_acc: AuthAccount) -> str | None:
        prefix = "@" if auth_acc.platform in ["ig", "tw", "tg"] else ""
        return f"Congratulations, {prefix}{auth_acc.username}! Your account was verified. Now you can accept card payments."


class TransferComplete(BaseNotification):
    category: Literal['payment complete'] = Field('payment complete')
    subcategory: Optional[str] = Field(None)
    transfer_id: uuid.UUID
    total_amount: Decimal
    currency: str
    message: str | None

    def user_message(self, auth_acc: AuthAccount) -> str | None:
        return (
            f"You received {self.total_amount} {self.currency}." +
            (f" Message: {self.message}." if self.message else '') +
            f" Transaction link: {Config.USER_UI_BASE}/payment_complete/{self.transfer_id}"
        )


class UserReferred(BaseNotification):
    category: Literal['user referred'] = Field('user referred')
    subcategory: Optional[str] = Field(None)
    referree: uuid.UUID


class TaskCompleted(BaseNotification):
    category: Literal['task completed'] = Field('task completed')
    task_result: Any


class NotificationData(RootModel[Union[
    UserRegistered,
    UserRestored,
    AccountCreated,
    AccountDeleted,
    UserDeleted,
    PayoutRequest,
    VerificationStarted,
    VerificationComplete,
    TransferComplete,
    UserReferred,
    TaskCompleted,
]]):
    pass


class Notification(BaseModel):
    notification_id: uuid.UUID
    created_at: datetime
    creator_id: uuid.UUID
    data: NotificationData


