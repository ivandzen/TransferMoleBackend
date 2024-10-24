import decimal
from typing import Dict, ClassVar
from psycopg2.extensions import cursor
import logging

from .stripe_bank_account_provider import StripeBankPayoutProvider
from .windapp_bank_account_provider import WindappBankAccountProvider
from .self_custody_crypto_provider import SelfCustodyCryptoProvider
from .circle_provider import CircleProvider
from .mercuryo_payout_provider import MercuryoPayoutProvider
from .payout_provider import PayoutProvider, ProviderParameters
from ...common.api_error import APIError


logger = logging.getLogger(__name__)


class ProviderNotFoundByPayout(APIError):
    def __init__(self, channel_type: str, provider_name: str | None, country_name: str):
        APIError.__init__(
            self,
            APIError.INTERNAL,
            f"{channel_type} payouts "
            f"{f'(of provider {provider_name})' if provider_name else ''}"
            f" are not available in {country_name}"
        )


PROVIDER_STRIPE = StripeBankPayoutProvider(
    default_fee=decimal.Decimal(0),
    transfer_min_usd=None,
    transfer_max_usd=None,
)

PROVIDER_WINDAPP = WindappBankAccountProvider(
    default_fee=decimal.Decimal(0),
    transfer_min_usd=None,
    transfer_max_usd=None,
)

PROVIDER_ETHEREUM = SelfCustodyCryptoProvider(
    network="Ethereum",
    default_fee=decimal.Decimal(0),
    transfer_min_usd=None,
    transfer_max_usd=None,
)

PROVIDER_POLYGON = SelfCustodyCryptoProvider(
    network="Polygon",
    default_fee=decimal.Decimal(0),
    transfer_min_usd=None,
    transfer_max_usd=None,
)

PROVIDER_AVALANCHE = SelfCustodyCryptoProvider(
    network="Avalanche C-Chain",
    default_fee=decimal.Decimal(0),
    transfer_min_usd=None,
    transfer_max_usd=None,
)

PROVIDER_BASE = SelfCustodyCryptoProvider(
    network="Base",
    default_fee=decimal.Decimal(0),
    transfer_min_usd=None,
    transfer_max_usd=None,
)

PROVIDER_BSC = SelfCustodyCryptoProvider(
    network="BSC",
    default_fee=decimal.Decimal(0),
    transfer_min_usd=None,
    transfer_max_usd=None,
)

PROVIDER_MERCURYO = MercuryoPayoutProvider(
    default_fee=decimal.Decimal(0),
    transfer_min_usd=None,
    transfer_max_usd=None,
)

PROVIDER_CIRCLE = CircleProvider(
    default_fee=decimal.Decimal(0),
    transfer_min_usd=None,
    transfer_max_usd=None,
)


class PayoutProviders:
    CACHE: ClassVar[Dict[str, PayoutProvider]] = {}

    @classmethod
    def update_cache(cls, cur: cursor) -> None:
        logger.info(f"Updating PayoutProvider cache...")
        cur.execute(
            "SELECT name, default_fee, transfer_min_usd, transfer_max_usd FROM public.payout_provider;",
        )

        provider_params = {
            entry[0]: ProviderParameters(default_fee=entry[1], transfer_min_usd=entry[2], transfer_max_usd=entry[3])
            for entry in cur
        }

        for provider_name, params in provider_params.items():
            match provider_name:
                case PROVIDER_STRIPE.name:
                    PROVIDER_STRIPE.set_parameters(params, cur)
                    cls.CACHE[provider_name] = PROVIDER_STRIPE

                case PROVIDER_WINDAPP.name:
                    PROVIDER_WINDAPP.set_parameters(params, cur)
                    cls.CACHE[provider_name] = PROVIDER_WINDAPP

                case PROVIDER_ETHEREUM.name:
                    PROVIDER_ETHEREUM.set_parameters(params, cur)
                    cls.CACHE[provider_name] = PROVIDER_ETHEREUM

                case PROVIDER_POLYGON.name:
                    PROVIDER_POLYGON.set_parameters(params, cur)
                    cls.CACHE[provider_name] = PROVIDER_POLYGON

                case PROVIDER_BSC.name:
                    PROVIDER_BSC.set_parameters(params, cur)
                    cls.CACHE[provider_name] = PROVIDER_BSC

                case PROVIDER_AVALANCHE.name:
                    PROVIDER_AVALANCHE.set_parameters(params, cur)
                    cls.CACHE[provider_name] = PROVIDER_AVALANCHE

                case PROVIDER_BASE.name:
                    PROVIDER_BASE.set_parameters(params, cur)
                    cls.CACHE[provider_name] = PROVIDER_BASE

                case PROVIDER_MERCURYO.name:
                    PROVIDER_MERCURYO.set_parameters(params, cur)
                    cls.CACHE[provider_name] = PROVIDER_MERCURYO

                case PROVIDER_CIRCLE.name:
                    PROVIDER_CIRCLE.set_parameters(params, cur)
                    cls.CACHE[provider_name] = PROVIDER_CIRCLE

                case unknown:
                    logger.warning(f"Unknown payout provider {unknown}")

        logger.info(f"Available payout providers: {PayoutProviders.CACHE.keys()}")

    @classmethod
    def get_provider(cls, name: str) -> PayoutProvider:
        provider = cls.CACHE.get(name, None)
        if not provider:
            raise APIError(APIError.OBJECT_NOT_FOUND, f"Payout provider {name} is not supported")

        return provider
