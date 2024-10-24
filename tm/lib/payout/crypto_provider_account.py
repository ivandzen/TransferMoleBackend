import uuid
from decimal import Decimal
from psycopg2.extensions import cursor
from pydantic import Field

from ..crypto_network import CryptoNetworks
from ..common.api_error import APIError
from ..creator import Creator
from .crypto_account import CryptoPayoutChannel
from ..payout.provider_account import ProviderAccount, logger
from .payment_intent import PaymentData, PaymentIntent


class CryptoProviderAccount(ProviderAccount):
    payout_channel: CryptoPayoutChannel = Field(exclude=True)

    def validate_existing_transaction(self, amount: Decimal, external_id: str) -> None:
        network = CryptoNetworks.get(self.payout_channel.data.network)
        network.check_transaction(
            external_id, self.payout_channel.data.address, self.payout_channel.currency, amount
        )

    def receive_payment(
            self,
            payment_type: str,
            recipient: Creator,
            transfer_id: uuid.UUID,
            amount: Decimal | None,
            collect_fee: bool,
            cur: cursor,
    ) -> PaymentIntent:
        if not amount:
            raise APIError(APIError.PAYMENT, f"amount is not specified")

        if payment_type != f"crypto:{self.payout_channel.data.network}":
            msg = (f"{payment_type} payments are not supported by selected "
                   f"account {self.payout_channel.channel_id}")
            logger.error(msg)
            raise APIError(APIError.INTERNAL, msg)

        network = CryptoNetworks.get(self.payout_channel.data.network)
        transaction = network.create_transaction(
            self.payout_channel.data.address, self.payout_channel.currency, amount
        )

        return PaymentIntent(
            transfer_id=transfer_id,
            currency=self.payout_channel.currency,
            payment_data=PaymentData(
                transaction=transaction,
                destination_crypto_address=self.payout_channel.data.address,
            ),
        )
