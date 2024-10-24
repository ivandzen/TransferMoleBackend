from psycopg2.extensions import cursor
import logging
from decimal import Decimal
from pydantic import Field
import uuid

from ..creator import Creator, VerificationStates
from .bank_account import BankPayoutChannel
from ..common.api_error import APIError
from .provider_account import ProviderAccount, create_new_provider_account
from .payment_intent import PaymentIntent
from ..payout.providers.payout_provider_cache import PROVIDER_WINDAPP

logger = logging.getLogger(__name__)


class WindappBankAccount(ProviderAccount):
    payout_channel: BankPayoutChannel = Field(exclude=True)

    @staticmethod
    def load(
            payout_channel: BankPayoutChannel,
            verification_states: VerificationStates,
            external_id: str | None
    ) -> "WindappBankAccount":
        return WindappBankAccount(
            provider=PROVIDER_WINDAPP,
            supported_payment_types=(
                ["internal:bank_account"]
                if verification_states.check_requirement("Internal") else []
            ),
            external_id=external_id,
            payout_channel=payout_channel,
        )

    @staticmethod
    def create_new(
            payout_channel: BankPayoutChannel,
            verification_states: VerificationStates,
            cur: cursor
    ) -> "WindappBankAccount":
        create_new_provider_account(
            channel_id=payout_channel.channel_id,
            provider=PROVIDER_WINDAPP.name,
            provider_data=None,
            external_id=None,
            cur=cur,
        )

        return WindappBankAccount.load(
            payout_channel=payout_channel,
            verification_states=verification_states,
            external_id=None
        )

    def validate_existing_transaction(self, amount: Decimal, external_id: str) -> None:
        # no validation logic for now
        pass

    def receive_payment(
            self,
            payment_type: str,
            recipient: Creator,
            transfer_id: uuid.UUID,
            amount: Decimal | None,
            collect_fee: bool,
            cur: cursor,
    ) -> PaymentIntent:
        match payment_type:
            case "internal:bank_account":
                return PaymentIntent(
                    transfer_id=transfer_id,
                    currency=self.payout_channel.currency
                )

            case unknown:
                msg = (f"{unknown} payments are not supported by selected "
                       f"account {self.payout_channel.channel_id}")
                logger.error(msg)
                raise APIError(APIError.INTERNAL, msg)
