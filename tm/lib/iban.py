import logging

from .payout.bank_account import BankAccountData, StripeExternalAccountParams
from .country_cache import CountryCache
from .common.api_error import APIError


logger = logging.getLogger(__name__)
TEST_PAYOUT_SUCCESSFUL_ACCOUNTS = {
    "Austria": "AT611904300234573201",
    "Belgium": "BE62510007547061",
    "Bulgaria": "BG80BNBG96611020345678",
    "Croatia": "HR7624020064583467589",
    "Cyprus": "CY17002001280000001200527600",
    "Czechia": "CZ6508000000192000145399",
    "Denmark": "DK5000400440116243",
    "Estonia": "EE382200221020145685",
    "Finland": "FI2112345600000785",
    "France": "FR1420041010050500013M02606",
    "Germany": "DE89370400440532013000",
    "Gibraltar": "GI75NWBK000000007099453",
    "Greece": "GR1601101250000000012300695",
    "Hungary": "HU42117730161111101800000000",
    "Ireland": "IE29AIBK93115212345678",
    "Italy": "IT40S0542811101000000123456",
    "Latvia": "LV80BANK0000435195001",
    "Liechtenstein": "LI0508800636123378777",
    "Lithuania": "LT121000011101001000",
    "Luxembourg": "LU280019400644750000",
    "Malta": "MT84MALT011000012345MTLCAST001S",
    "Netherlands": "NL39RABO0300065264",
    "Norway": "NO9386011117947",
    "Poland": "PL61109010140000071219812874",
    "Portugal": "PT50000201231234567890154",
    "Romania": "RO49AAAA1B31007593840000",
    "Slovakia": "SK3112000000198742637541",
    "Slovenia": "SI56263300012039086",
    "Spain": "ES0700120345030000067890",
    "Sweden": "SE3550000000054910000003",
    "Switzerland": "CH9300762011623852957",
}


def parse_iban_bank_account(
        account_data: BankAccountData,
        use_test_account: bool,
) -> StripeExternalAccountParams:
    country = CountryCache.get_country(account_data.country)
    result = StripeExternalAccountParams(
        country=country.code,
        account_holder_type=account_data.account_holder_type,
        account_holder_name=account_data.account_holder_name,
        routing_number=None,
        account_number=account_data.account_number,
        currency=account_data.currency,
        object="bank_account",
    )

    if use_test_account:
        test_acc_number = TEST_PAYOUT_SUCCESSFUL_ACCOUNTS.get(country.name)
        if test_acc_number is None:
            raise APIError(
                APIError.INTERNAL,
                f"Test account not found for country {country.name}"
            )
        result["account_number"] = test_acc_number

    return result
