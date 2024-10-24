from uuid import UUID
from decimal import Decimal
from pydantic import Field
import logging
from psycopg2.extensions import cursor
import hashlib
import urllib.parse

from ..creator import Creator, VerificationStates
from ..verification.mercuryo_user import MercuryoUser
from ..common.config import Config
from ..common.api_error import APIError
from .crypto_account import CryptoPayoutChannel
from .provider_account import (ProviderAccount, create_new_provider_account)
from .payment_intent import PaymentData, PaymentIntent
from .providers.payout_provider_cache import PROVIDER_MERCURYO, PROVIDER_ETHEREUM, PROVIDER_POLYGON

logger = logging.getLogger(__name__)
SANDBOX_ETH_WALLET_ADDR = "0xA14691F9f1F851bd0c20115Ec10B25FC174371DF"
MERCURYO_BASE_URL={
    "Sandbox": "https://sandbox-exchange.mrcr.io",
    "Prod": "https://exchange.mercuryo.io",
}

MERCURYO_NETWORK_NAME = {
    PROVIDER_ETHEREUM.name: "ETHEREUM",
    PROVIDER_POLYGON.name: "POLYGON"
}


class MercuryoCryptoProviderAccount(ProviderAccount):
    payout_channel: CryptoPayoutChannel = Field(exclude=True)

    @staticmethod
    def load(
            payout_channel: CryptoPayoutChannel,
            verification_states: VerificationStates,
            external_id: str | None,
    ) -> "MercuryoCryptoProviderAccount":
        available_payments = ["card"]
        if verification_states.check_requirement("Sumsub"):
            available_payments.append("onramp")

        return MercuryoCryptoProviderAccount(
            provider=PROVIDER_MERCURYO,
            supported_payment_types=available_payments,
            external_id=external_id,
            payout_channel=payout_channel,
        )

    @staticmethod
    def create_new(
            payout_channel: CryptoPayoutChannel,
            verification_states: VerificationStates,
            cur: cursor
    ) -> 'MercuryoCryptoProviderAccount':
        create_new_provider_account(
            channel_id=payout_channel.channel_id,
            provider=PROVIDER_MERCURYO.name,
            provider_data=None,
            external_id=None,
            cur=cur,
        )

        return MercuryoCryptoProviderAccount.load(
            payout_channel=payout_channel,
            verification_states=verification_states,
            external_id=None
        )

    def _create_payment_intent(
            self, creator: Creator, transfer_id: UUID, mercuryo_user: MercuryoUser | None
    ) -> PaymentIntent:
        if Config.MERCURYO_MODE == "Sandbox" and self.payout_channel.data.network != PROVIDER_ETHEREUM.name:
            raise APIError(
                APIError.INTERNAL,
                f"Only Ethereum wallets are supported in Sandbox mode"
            )

        hasher = hashlib.sha512()
        wallet_address = SANDBOX_ETH_WALLET_ADDR \
            if Config.MERCURYO_MODE == "Sandbox" \
            else self.payout_channel.data.address

        hasher.update(f"{wallet_address}{Config.MERCURYO_SECRET}".encode('utf-8'))
        redirect_url = urllib.parse.quote_plus(f"{Config.USER_UI_BASE}/payment_complete/{transfer_id}")
        payment_url = (f"{MERCURYO_BASE_URL[Config.MERCURYO_MODE]}/?"
                       f"widget_id={Config.MERCURYO_WIDGET_ID}"
                       f"&partner_flow=jupiter"
                       f"&fiat_currency=USD&currency="
                       f"{self.payout_channel.data.currency if Config.MERCURYO_MODE != 'Sandbox' else 'USDT'}"
                       f"&network={MERCURYO_NETWORK_NAME[self.payout_channel.data.network]}"
                       f"&address={wallet_address}"
                       f"&merchant_transaction_id={transfer_id}"
                       f"&redirect_url={redirect_url}"
                       f"&return_url={redirect_url}"
                       f"&fix_currency=true"
                       f"&fix_fiat_currency=true"
                       f"&fix_network={MERCURYO_NETWORK_NAME[self.payout_channel.data.network]}"
                       f"&hide_address=true"
                       f"&signature={hasher.hexdigest()}")

        if mercuryo_user:
            payment_url += f"init_token_type=sdk_partner_authorization&init_token={mercuryo_user.init_token}"

        return PaymentIntent(
            transfer_id=transfer_id,
            currency="USD",
            payment_data=PaymentData(payment_url=payment_url)
        )

    def receive_payment(
            self,
            payment_type: str,
            recipient: Creator,
            transfer_id: UUID,
            amount: Decimal | None,
            collect_fee: bool,
            cur: cursor,
    ) -> PaymentIntent:
        match payment_type:
            case "onramp":
                if "onramp" not in self.supported_payment_types:
                    raise APIError(
                        APIError.INTERNAL,
                        f"Complete identity verification to enable crypto purchases"
                    )

                return self._create_payment_intent(
                    creator=recipient,
                    transfer_id=transfer_id,
                    mercuryo_user=MercuryoUser.get_or_create_new_linked(
                        creator=recipient,
                        cur=cur
                    )
                )

            case "card":
                return self._create_payment_intent(
                    creator=recipient,
                    transfer_id=transfer_id,
                    mercuryo_user=None
                )

            case unknown:
                msg = (f"{unknown} payments are not supported by selected "
                       f"account {self.payout_channel.channel_id}")
                logger.error(msg)
                raise APIError(APIError.INTERNAL, msg)
