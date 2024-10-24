import logging
from psycopg2.extensions import cursor

from .crypto_account import CryptoPayoutChannel
from .provider_account import create_new_provider_account
from .crypto_provider_account import CryptoProviderAccount
from .providers.payout_provider_cache import PayoutProviders

logger = logging.getLogger(__name__)


class SelfCustodyCryptoWallet(CryptoProviderAccount):
    @staticmethod
    def load(payout_channel: CryptoPayoutChannel) -> "SelfCustodyCryptoWallet":
        return SelfCustodyCryptoWallet(
            provider=PayoutProviders.get_provider(payout_channel.data.network),
            supported_payment_types=[f"crypto:{payout_channel.data.network}"],
            external_id=payout_channel.data.address,
            payout_channel=payout_channel,
        )

    @staticmethod
    def create_new(
            payout_channel: CryptoPayoutChannel,
            cur: cursor,
    ) -> "SelfCustodyCryptoWallet":
        create_new_provider_account(
            channel_id=payout_channel.channel_id,
            provider=payout_channel.data.network,
            provider_data=None,
            external_id=payout_channel.data.address,
            cur=cur,
        )

        return SelfCustodyCryptoWallet.load(payout_channel)
