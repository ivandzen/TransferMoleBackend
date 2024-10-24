from .payout.bank_account import BankAccountData, StripeExternalAccountParams
import logging

from .country_cache import CountryCache


logger = logging.getLogger(__name__)


def parse_canada_bank_account(
        account_data: BankAccountData,
        use_test_account: bool,
) -> StripeExternalAccountParams:
    country = CountryCache.get_country(account_data.country)
    result = StripeExternalAccountParams(
        country=country.code,
        account_holder_type=account_data.account_holder_type,
        account_holder_name=account_data.account_holder_name,
        routing_number=f"{account_data.transit_number}-{account_data.institution_number}",
        account_number=account_data.account_number,
        currency=account_data.currency,
        object="bank_account",
    )

    if use_test_account:
        result["routing_number"] = '11000-000'
        result["account_number"] = '000123456789'

    return result