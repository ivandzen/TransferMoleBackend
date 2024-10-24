import logging
from pydantic import BaseModel, computed_field
from typing import Optional
from decimal import Decimal
from psycopg2.extensions import cursor

from ...common.config import Config
from ...redis_cache import CachedObject

logger = logging.getLogger(__name__)


class ProviderParameters(BaseModel):
    default_fee: Decimal
    transfer_min_usd: Optional[Decimal] = None
    transfer_max_usd: Optional[Decimal] = None


class PayoutProviderData(BaseModel):
    name: str
    params: ProviderParameters


class PayoutProvider(CachedObject[PayoutProviderData]):
    def set_parameters(
            self,
            params: ProviderParameters,
            cur: cursor
    ) -> None:
        cur.execute(
            "UPDATE public.payout_provider "
            "SET default_fee = %s, transfer_min_usd = %s, transfer_max_usd = %s "
            "WHERE name = %s;",
            (params.default_fee, params.transfer_min_usd, params.transfer_max_usd, self.name,)
        )
        self.params = params

    @computed_field # type: ignore
    @property
    def name(self) -> str:
        return self.instance.name

    @computed_field # type: ignore
    @property
    def transfer_min_usd(self) -> Decimal:
        return (Config.TRANSFER_MINIMUM_USD
                if not self.instance.params.transfer_min_usd
                else self.instance.params.transfer_min_usd)

    @computed_field # type: ignore
    @property
    def transfer_max_usd(self) -> Decimal:
        return (Config.TRANSFER_MAXIMUM_USD
                if not self.instance.params.transfer_max_usd
                else self.instance.params.transfer_max_usd)

    @computed_field # type: ignore
    @property
    def provider_fee_usd(self) -> Decimal:
        return self.instance.params.default_fee
