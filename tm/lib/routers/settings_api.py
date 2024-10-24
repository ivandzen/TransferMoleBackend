from aiohttp.log import client_logger
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional, Annotated
import logging
from decimal import Decimal

from ..country_cache import CountryCache
from ..payout.account_factory import AvailablePayoutChannels, AccountFactory
from ..iplocation import get_ip_location
from ..crypto_network import CryptoNetwork, CryptoNetworks
from ..currency import Currency
from ..advanced_form import AdvancedForm
from .common import required_access_token_ctx, Context


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])


class CountryRequirements(BaseModel):
    available_payout_channels: AvailablePayoutChannels
    personal_info_reqs: Optional[Dict[str, Any]] = None
    bank_account_reqs: Optional[Dict[str, Any]] = None


@router.get(
    path="/requirements/{country}",
    operation_id='get_country_requirements',
    response_model=CountryRequirements,
)
async def get_country_requirements(
        country_name: str
) -> CountryRequirements:
    country = CountryCache.get_country(country_name)
    return CountryRequirements(
        available_payout_channels=AccountFactory.get_available_payout_channels(country),
        personal_info_reqs=country.individual_requirements.model_dump() if country.individual_requirements else None,
        bank_account_reqs=country.bank_account_requirements.model_dump() if country.bank_account_requirements else None,
    )


@router.get(
    path="/requirements/{country}/bank_account",
    operation_id='get_country_bank_account_requirements',
    response_model=AdvancedForm,
)
async def get_country_bank_account_requirements(
        country_name: str
) -> AdvancedForm:
    country = CountryCache.get_country(country_name)
    return country.get_bank_account_requirements()


@router.get(
    path="/requirements/{country}/individual",
    operation_id='get_country_individual_requirements',
    response_model=AdvancedForm,
)
async def get_country_individual_requirements(
        country_name: str
) -> AdvancedForm:
    country = CountryCache.get_country(country_name)
    return country.get_individual_requirements()


@router.get(
    path="/client_ip",
    operation_id='get_client_country',
    response_model=str | None,
)
async def get_client_country(context: Annotated[Context, Depends(required_access_token_ctx)]) -> str | None:
    if not context.client_ip:
        return None

    country = get_ip_location(context.client_ip)
    if not country:
        return None

    return country.name


@router.get(
    path="/crypto_networks",
    operation_id='get_crypto_networks',
    response_model=Dict[str, CryptoNetwork]
)
async def get_crypto_networks() -> Dict[str, CryptoNetwork]:
    result = {}
    for network_name, network in CryptoNetworks.items():
        result[network_name] = network
    return result


@router.get(
    path="/exchange_rates",
    operation_id='get_exchange_rates',
    response_model=Dict[str, Decimal],
)
async def get_exchange_rates() -> Dict[str, Decimal]:
    return Currency.get_exchange_rates().root
