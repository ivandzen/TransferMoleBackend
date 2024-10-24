from decimal import Decimal

from .payout_provider import PayoutProvider, PayoutProviderData, ProviderParameters


class WindappBankAccountProvider(PayoutProvider):
    def __init__(
            self,
            default_fee: Decimal,
            transfer_min_usd: Decimal | None,
            transfer_max_usd: Decimal | None
    ):
        PayoutProvider.__init__(
            self,
            cache_key=f"PayoutProvider.Windapp",
            cls=PayoutProviderData,
            instance=PayoutProviderData(
                name="Windapp",
                params=ProviderParameters(
                    default_fee=default_fee,
                    transfer_min_usd=transfer_min_usd,
                    transfer_max_usd=transfer_max_usd,
                ),
            )
        )
