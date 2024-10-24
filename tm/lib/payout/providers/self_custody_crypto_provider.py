from decimal import Decimal
from .payout_provider import PayoutProvider, ProviderParameters, PayoutProviderData


class SelfCustodyCryptoProvider(PayoutProvider):
    def __init__(
            self,
            network: str,
            default_fee: Decimal,
            transfer_min_usd: Decimal | None,
            transfer_max_usd: Decimal | None
    ):
        PayoutProvider.__init__(
            self,
            cache_key=f"PayoutProvider.{network}",
            cls=PayoutProviderData,
            instance=PayoutProviderData(
                name=network,
                params=ProviderParameters(
                    default_fee=default_fee,
                    transfer_min_usd=transfer_min_usd,
                    transfer_max_usd=transfer_max_usd,
                ),
            )
        )
