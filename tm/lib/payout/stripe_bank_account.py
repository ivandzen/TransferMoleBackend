import logging
import uuid
from decimal import Decimal
from pydantic import BaseModel, Field
from typing import Optional, Tuple, Union

import stripe
from psycopg2.extensions import cursor
from ..common.api_error import APIError
from ..common.config import Config
from ..singapore import parse_singapore_bank_account
from ..australia import parse_australia_bank_account
from ..canada import parse_canada_bank_account
from ..new_zealand import parse_new_zealand_bank_account
from ..hong_kong import parse_hong_kong_bank_account
from ..united_kingdom import parse_united_kingdom_bank_account
from ..united_states import parse_united_states_bank_account
from ..iban import parse_iban_bank_account
from .provider_account import ProviderAccount, create_new_provider_account
from .payment_intent import PaymentData, PaymentIntent
from ..advanced_form import AdvancedForm
from ..verification.stripe_account import StripeAccount
from .bank_account import BankAccountData, IBAN_COUNTRIES, StripeExternalAccountParams, BankPayoutChannel
from ..authentication.auth_account import get_platform_name
from ..creator import Creator, VerificationStates
from .providers.payout_provider_cache import PROVIDER_STRIPE
from ..authentication.auth_account_factory import AuthAccountFactory

logger = logging.getLogger(__name__)


def get_usernames_string(recipient: Creator, cur: cursor) -> str:
    auth_accounts = AuthAccountFactory.load_creator_accounts(recipient.creator_id, cur)
    if len(auth_accounts) > 0:
        return f"{auth_accounts[0].username} ({get_platform_name(auth_accounts[0].platform)})"

    raise APIError(
        APIError.INTERNAL,
        f"Authentication account not found"
    )


def convert_to_stripe_bank_account_data(
        country_name: str,
        account_data: BankAccountData,
        stripe_test_mode: bool,
        bank_requirements: AdvancedForm,
) -> StripeExternalAccountParams | None:
    if country_name in IBAN_COUNTRIES:
        return parse_iban_bank_account(
            account_data=account_data,
            use_test_account=stripe_test_mode,
        )

    if country_name == "Australia":
        return parse_australia_bank_account(
            account_data=account_data,
            use_test_account=stripe_test_mode,
        )

    if country_name == "Canada":
        return parse_canada_bank_account(
            account_data=account_data,
            use_test_account=stripe_test_mode,
        )

    if country_name == "Hong Kong":
        return parse_hong_kong_bank_account(
            account_data=account_data,
            use_test_account=stripe_test_mode,
            bank_requirements=bank_requirements,
        )

    if country_name == "New Zealand":
        return parse_new_zealand_bank_account(
            account_data=account_data,
            use_test_account=stripe_test_mode,
        )

    if country_name == "Singapore":
        return parse_singapore_bank_account(
            account_data=account_data,
            use_test_account=stripe_test_mode,
            bank_requirements=bank_requirements
        )

    if country_name == "United Kingdom of Great Britain and Northern Ireland":
        return parse_united_kingdom_bank_account(
            account_data=account_data,
            use_test_account=stripe_test_mode,
        )

    if country_name == "United States of America":
        return parse_united_states_bank_account(
            account_data=account_data,
            use_test_account=stripe_test_mode,
        )

    logger.warning(f"Stripe bank accounts are not supported at '{country_name}'")
    raise APIError(
        APIError.STRIPE_NOT_SUPPORTED,
        f"Stripe bank accounts are not supported at {country_name} yet"
    )


class StripeBankAccountProviderData(BaseModel):
    stripe_account: str


class StripeBankAccount(ProviderAccount):
    payout_channel: BankPayoutChannel = Field(exclude=True)
    provider_data: Optional[StripeBankAccountProviderData]

    @staticmethod
    def load(
            payout_channel: BankPayoutChannel,
            verification_states: VerificationStates,
            provider_data: StripeBankAccountProviderData | None,
            external_id: str | None,
    ) -> "StripeBankAccount":
        return StripeBankAccount(
            provider=PROVIDER_STRIPE,
            supported_payment_types=(
                ["card", "internal:bank_account"]
                if verification_states.check_requirement("Stripe") else []
            ),
            external_id=external_id,
            payout_channel=payout_channel,
            provider_data=provider_data,
        )

    @staticmethod
    def create_new(
            creator: Creator,
            payout_channel: BankPayoutChannel,
            verification_states: VerificationStates,
            stripe_bank_account: stripe.BankAccount | None,
            cur: cursor,
    ) -> "StripeBankAccount":
        if not creator.country:
            raise APIError(APIError.CREATOR_COUNTRY_NOT_SELECTED, "Country not set")

        create_new_provider_account(
            channel_id=payout_channel.channel_id,
            provider=PROVIDER_STRIPE.name,
            provider_data=None,
            external_id=None,
            cur=cur,
        )

        stripe_bank_acc = StripeBankAccount.load(
            payout_channel=payout_channel,
            verification_states=verification_states,
            provider_data=None, external_id=None
        )

        if stripe_bank_account:
            stripe_bank_acc.attach_stripe_bank_account(stripe_bank_account, cur)
        else:
            if verification_states.check_requirement("Stripe"):
                stripe_account = StripeAccount.get_account_by_creator_id(creator.creator_id, cur)
                if not stripe_account:
                    logger.warning(f"Stripe account not found for creator {creator.creator_id}")
                    raise APIError(APIError.OBJECT_NOT_FOUND, "Verification account not found")

                stripe_bank_acc.create_stripe_bank_account(
                    stripe_account=stripe_account.account_id,
                    stripe_test_mode=not Config.PRODUCTION,
                    bank_requirements=creator.country.get_bank_account_requirements(),
                    cur=cur
                )

        return stripe_bank_acc

    def update(self, provider_data: StripeBankAccountProviderData, external_id: str | None, cur: cursor) -> None:
        old_provider_data = self.provider_data.model_dump_json() if self.provider_data else None
        cur.execute(
            f"UPDATE public.provider_account "
            f"SET provider_data = %s, external_id = %s "
            f"WHERE channel_id = %s;",
            (provider_data.model_dump_json() if provider_data else old_provider_data,
             external_id if external_id else self.external_id, self.payout_channel.channel_id,)
        )

    @property
    def stripe_account(self) -> str | None:
        return self.provider_data.stripe_account if self.provider_data else None

    def _get_stripe_external_account(self) -> Union[stripe.BankAccount, stripe.Card]:
        if self.stripe_account is None:
            raise APIError(APIError.INTERNAL, "Verification account not set")

        if self.external_id is None:
            raise APIError(APIError.INTERNAL, "External ID not set for bank account")

        return stripe.Account.retrieve_external_account(
            self.stripe_account, api_key=Config.STRIPE_USER, id=self.external_id
        )

    def attach_stripe_bank_account(
            self,
            stripe_bank_account: stripe.BankAccount,
            cur: cursor
    ) -> None:
        if self.is_complete():
            return

        self.update(
            provider_data=StripeBankAccountProviderData(stripe_account=stripe_bank_account.account),
            external_id=stripe_bank_account.id,
            cur=cur,
        )

    def create_stripe_bank_account(
            self,
            stripe_account: str,  # parent stripe account
            stripe_test_mode: bool,
            bank_requirements: AdvancedForm,
            cur: cursor
    ) -> None:
        if self.is_complete():
            return

        stripe_compatible_data = convert_to_stripe_bank_account_data(
            country_name=self.payout_channel.data.country,
            account_data=self.payout_channel.data,
            stripe_test_mode=stripe_test_mode,
            bank_requirements=bank_requirements,
        )

        try:
            token = stripe.Token.create(api_key=Config.STRIPE_USER, bank_account=stripe_compatible_data.__dict__)
            external_acc = stripe.Account.create_external_account(
                stripe_account, api_key=Config.STRIPE_USER, external_account=token.id
            )
        except Exception as _:
            raise APIError(
                APIError.INTERNAL,
                f"Error of underlying protocol. Contact support please."
            )

        self.update(
            provider_data=StripeBankAccountProviderData(stripe_account=stripe_account),
            external_id=external_acc.id,
            cur=cur,
        )

    def is_complete(self) -> bool:
        return (self.stripe_account is not None
                and self.external_id is not None)

    def validate_existing_transaction(self, amount: Decimal, external_id: str) -> None:
        if not self.is_complete():
            raise APIError(
                APIError.PAYMENT,
                f"Account {self.payout_channel.channel_id} is not ready to receive payouts"
            )

        stripe.api_key = Config.STRIPE_USER
        try:
            transfer = stripe.Transfer.retrieve(external_id)
        except Exception as e:
            logger.error(f"Stripe error {e}")
            raise APIError(
                APIError.INTERNAL,
                f"Error of underlying protocol"
            )

        if transfer.destination != self.stripe_account:
            raise APIError(
                APIError.PAYMENT,
                f"Stripe account ID does not match. "
                f"Expected {self.stripe_account} but got {transfer.destination}"
            )

        actual_amount = Decimal(transfer.amount) / 100
        if actual_amount != amount:
            raise APIError(
                APIError.PAYMENT,
                f"Amount does not match. Expected {amount} but got {actual_amount}"
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
        match payment_type:
            case "card":
                return self.receive_card_payment(
                    recipient=recipient,
                    transfer_id=transfer_id,
                    collect_fee=collect_fee,
                    cur=cur,
                )
            case "internal:bank_account":
                return PaymentIntent(
                    transfer_id=transfer_id,
                    currency=self.payout_channel.currency,
                )

            case unknown:
                msg = (f"{unknown} payments are not supported by selected "
                       f"account {self.payout_channel.channel_id}")
                logger.error(msg)
                raise APIError(APIError.INTERNAL, msg)

    def receive_card_payment(
            self,
            recipient: Creator,
            transfer_id: uuid.UUID,
            collect_fee: bool,
            cur: cursor,
    ) -> PaymentIntent:
        if not self.is_complete():
            raise APIError(
                APIError.INTERNAL,
                f"Receiver is not ready to accept payments"
            )

        price_id = StripeAccount.get_price(
            stripe_account=self.stripe_account,
            creator_id=recipient.creator_id,
            currency='usd',
            description=f"Payment for {get_usernames_string(recipient, cur)}",
            cur=cur
        )
        success_url = Config.USER_UI_BASE + f'/payment_complete/{str(transfer_id)}'
        cancel_url = recipient.get_payment_link()

        try:
            checkout_session = stripe.checkout.Session.create(
                api_key=Config.STRIPE_USER,
                stripe_account=self.stripe_account,
                billing_address_collection='auto',
                line_items=[{
                    'price': price_id,
                    'quantity': 1,
                }],
                mode='payment',
                automatic_tax={'enabled': False},
                phone_number_collection={'enabled': False},
                tax_id_collection={'enabled': False},
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=str(transfer_id),
                currency='USD',
                invoice_creation={'enabled': False},
                consent_collection={'terms_of_service': 'none'},
                payment_intent_data={
                    'application_fee_amount': Config.TRANSFERMOLE_FEE_USD if collect_fee else 0,
                },
            )

            return PaymentIntent(
                transfer_id=transfer_id,
                currency='USD',
                external_id=checkout_session['id'],
                payment_data=PaymentData(payment_url=checkout_session['url'])
            )
        except Exception as e:
            logger.warning(f"Failed to create checkout session: {e}")
            raise APIError(APIError.INTERNAL, "Failed to create checkout session")
