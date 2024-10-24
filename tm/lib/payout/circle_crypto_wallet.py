import logging
from psycopg2.extensions import cursor

from .crypto_account import CryptoPayoutChannel
from .provider_account import create_new_provider_account
from .crypto_provider_account import CryptoProviderAccount
from .providers.payout_provider_cache import PROVIDER_CIRCLE

logger = logging.getLogger(__name__)


class CircleCryptoWallet(CryptoProviderAccount):
    @staticmethod
    def load(
            payout_channel: CryptoPayoutChannel,
            external_id: str,
    ) -> "CircleCryptoWallet":
        assert (payout_channel.data.network == "Polygon")
        return CircleCryptoWallet(
            provider=PROVIDER_CIRCLE,
            supported_payment_types=[f"crypto:{payout_channel.data.network}"],
            external_id=external_id,
            payout_channel=payout_channel,
        )

    @staticmethod
    def create_new(
            payout_channel: CryptoPayoutChannel,
            external_id: str,
            cur: cursor,
    ) -> "CircleCryptoWallet":
        create_new_provider_account(
            channel_id=payout_channel.channel_id,
            provider=PROVIDER_CIRCLE.name,
            provider_data=None,
            external_id=external_id,
            cur=cur,
        )

        return CircleCryptoWallet.load(payout_channel, external_id)
