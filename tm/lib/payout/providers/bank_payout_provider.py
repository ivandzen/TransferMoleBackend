from ...common.api_error import APIError
from ...creator import Creator
from ..bank_account import BankAccountData


def check_bank_account_data(
        owner: Creator,
        data: dict,
) -> BankAccountData:
    if not owner.country:
        raise APIError(APIError.INTERNAL, "Country not set for user")

    bank_account_requirements = owner.country.get_bank_account_requirements()
    if not bank_account_requirements:
        raise APIError(
            APIError.CREATE_PAYOUT_CHANNEL_ERROR,
            f"Bank accounts are not yet supported in {owner.country.name}. Please, use crypto."
        )

    bank_account_requirements.check(data)
    return BankAccountData.model_validate(data)
