import logging

from .common.api_error import APIError
from .advanced_form import AdvancedForm
from .payout.bank_account import BankAccountData, StripeExternalAccountParams

logger = logging.getLogger(__name__)


def parse_singapore_bank_account(
        account_data: BankAccountData,
        use_test_account: bool,
        bank_requirements: AdvancedForm,
) -> StripeExternalAccountParams:
    if not bank_requirements.objects:
        logger.error("Bank requirements for Singapore does not contain objects")
        raise APIError(APIError.INTERNAL, "Unexpected error. Please, contact customer support")

    singapore_banks = bank_requirements.objects.get('banks', None)
    if not singapore_banks:
        logger.error(f"There's no banks objects for Singapore")
        raise APIError(APIError.INTERNAL)

    bank_obj = None
    for entry in singapore_banks:
        if (entry['bank_name'] == account_data.bank_name
                and entry['branch_name'] == account_data.branch_name):
            bank_obj = entry
            break

    if not bank_obj:
        raise APIError(
            APIError.BANK_ACCOUNT_INFO,
            f"Bank not found"
        )

    result = StripeExternalAccountParams(
        country='SG',
        account_holder_type=account_data.account_holder_type,
        account_holder_name=account_data.account_holder_name,
        routing_number=f"{bank_obj['bank_code']}-{bank_obj['branch_code']}",
        account_number=account_data.account_number,
        currency=account_data.currency,
        object="bank_account",
    )

    if use_test_account:
        result["routing_number"] = '1100-000'
        result["account_number"] = '000123456'
    return result
