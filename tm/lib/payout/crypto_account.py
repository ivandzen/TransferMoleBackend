import logging
import uuid
from psycopg2.extensions import cursor
from pydantic import BaseModel, model_validator

from .payout_channel import PayoutChannel, create_payout_channel
from ..crypto_network import CryptoNetworks
from ..common.api_error import APIError
from ..creator import Creator


logger = logging.getLogger(__name__)


class CryptoAccountDetails(BaseModel):
    network: str
    address: str
    currency: str

    @model_validator(mode="after")
    def validate_params(self) -> 'CryptoAccountDetails':
        network = CryptoNetworks.get(self.network)
        self.address = network.check_wallet_address(self.address)
        if self.currency not in network.currencies:
            raise APIError(
                APIError.INTERNAL,
                f"Currency {self.currency} is not supported yet on network {self.network}"
            )
        return self


class CryptoPayoutChannel(PayoutChannel):
    data: CryptoAccountDetails

    @staticmethod
    def create_new(
            creator: Creator,
            data: CryptoAccountDetails,
            cur: cursor,
    ) -> "CryptoPayoutChannel":
        channel_id = create_payout_channel(
            creator=creator,
            channel_type="crypto",
            data=data,
            currency=data.currency,
            cur=cur
        )

        return CryptoPayoutChannel(
            creator_id=creator.creator_id,
            channel_id=channel_id,
            channel_type="crypto",
            data=data,
            currency=data.currency,
            removed=False,
        )
