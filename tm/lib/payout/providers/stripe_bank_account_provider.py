import logging
from decimal import Decimal

from .payout_provider import PayoutProvider, PayoutProviderData, ProviderParameters


logger = logging.getLogger(__name__)


class StripeBankPayoutProvider(PayoutProvider):
    def __init__(
            self,
            default_fee: Decimal,
            transfer_min_usd: Decimal | None,
            transfer_max_usd: Decimal | None
    ):
        PayoutProvider.__init__(
            self,
            cache_key="PayoutProvider.Stripe",
            cls=PayoutProviderData,
            instance=PayoutProviderData(
                name="Stripe",
                params=ProviderParameters(
                    default_fee=default_fee,
                    transfer_min_usd=transfer_min_usd,
                    transfer_max_usd=transfer_max_usd,
                ),
            )
        )
