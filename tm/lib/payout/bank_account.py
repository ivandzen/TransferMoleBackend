import logging
from typing import Optional
from typing_extensions import TypedDict
from psycopg2.extensions import cursor
from pydantic import BaseModel

from .payout_channel import PayoutChannel, create_payout_channel
from ..creator import Creator

IBAN_COUNTRIES = {
    "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark", "Estonia", "Finland", "France",
    "Germany", "Gibraltar", "Greece", "Hungary", "Ireland", "Italy", "Latvia", "Liechtenstein", "Lithuania",
    "Luxembourg", "Malta", "Netherlands", "Norway", "Poland", "Portugal", "Romania", "Slovakia", "Slovenia", "Spain",
    "Sweden", "Switzerland",
}

logger = logging.getLogger(__name__)


class BankAccountData(BaseModel):
    country: str
    account_holder_type: str
    account_holder_name: str
    currency: str
    account_number: str
    routing_number: Optional[str] = None        # US
    bsb: Optional[str] = None                   # Australia
    transit_number: Optional[str] = None        # Canada
    institution_number: Optional[str] = None    # Canada
    bank_name: Optional[str] = None             # Hong Kong, Singapore
    branch_name: Optional[str] = None           # Hong Kong, Singapore
    sort_code: Optional[str] = None             # UK


class StripeExternalAccountParams(TypedDict):
    country: str
    account_holder_type: str
    account_holder_name: str
    routing_number: str | None
    account_number: str
    currency: str
    object: str


class BankPayoutChannel(PayoutChannel):
    data: BankAccountData

    @staticmethod
    def create_new(
            creator: Creator,
            data: BankAccountData,
            cur: cursor,
    ) -> "BankPayoutChannel":
        channel_id = create_payout_channel(
            creator=creator,
            channel_type="bank_account",
            data=data,
            currency=data.currency,
            cur=cur
        )

        return BankPayoutChannel(
            creator_id=creator.creator_id,
            channel_id=channel_id,
            channel_type="bank_account",
            data=data,
            currency=data.currency,
            removed=False,
        )
