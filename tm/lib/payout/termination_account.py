from psycopg2.extensions import cursor
from typing import List, Union
from pydantic import BaseModel

from .crypto_account import CryptoPayoutChannel
from .bank_account import BankPayoutChannel
from .stripe_bank_account import StripeBankAccount
from .windapp_bank_account import WindappBankAccount
from .self_custody_crypto_wallet import SelfCustodyCryptoWallet
from .mercuryo_crypto_provider_account import MercuryoCryptoProviderAccount
from .circle_crypto_wallet import CircleCryptoWallet
from ..notification import AccountDeleted
from ..notification_utils import send_notification

PayoutChannelType = Union[
    BankPayoutChannel,
    CryptoPayoutChannel
]

ProviderAccountType = Union[
    StripeBankAccount,
    WindappBankAccount,
    SelfCustodyCryptoWallet,
    MercuryoCryptoProviderAccount,
    CircleCryptoWallet,
]


class TerminationAccount(BaseModel):
    payout_channel: PayoutChannelType
    provider_accounts: List[ProviderAccountType]

    def remove(self, cur: cursor) -> None:
        self.payout_channel.remove(cur)
        for provider_account in self.provider_accounts:
            provider_account.remove(cur)

        send_notification(
            self.payout_channel.creator_id,
            AccountDeleted(
                channel_id=self.payout_channel.channel_id,
                type=self.payout_channel.channel_type
            ),
            None,
        )
