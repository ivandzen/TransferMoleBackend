import logging
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from .common.api_error import APIError
from .advanced_form import AdvancedForm

logger = logging.getLogger(__name__)


class Country(BaseModel):
    name: str
    code: str
    bank_account_requirements: Optional[AdvancedForm] = Field(None, exclude=True)
    individual_requirements: Optional[AdvancedForm] = Field(None, exclude=True)
    payout_providers: list[str]
    kyc_providers: list[str]

    def get_bank_account_requirements(self) -> AdvancedForm:
        if self.bank_account_requirements:
            return self.bank_account_requirements

        raise APIError(
            APIError.CREATE_PAYOUT_CHANNEL_ERROR,
            f"Bank accounts are not yet supported in {self.name}."
        )

    def get_individual_requirements(self) -> AdvancedForm:
        if self.individual_requirements:
            return self.individual_requirements

        raise APIError(
            APIError.OBJECT_NOT_FOUND,
            f"Individual requirements for {self.name} not found"
        )

    def check_personal_info(self, personal_info: Dict[str, Any], soft_mode: bool = True) -> Dict[str, Any]:
        requirements = self.get_individual_requirements()
        return requirements.check(personal_info, soft_mode)
