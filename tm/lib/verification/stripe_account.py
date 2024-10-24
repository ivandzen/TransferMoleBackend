import datetime
import uuid
from psycopg2.extensions import cursor
import stripe
import logging
from dataclasses import dataclass
from pydantic import BaseModel, Field
from typing import Dict, Any

from ..common.config import Config
from ..country_codes import country_codes
from ..currency import convert_usd_to_currency


logger = logging.getLogger(__name__)


class StripeVerificationError(BaseModel):
    requirement: str
    code: str
    reason: str


class StripeRequirements(BaseModel):
    eventually_due: list[str] = Field(default=[])
    pending_verification: list[str] = Field(default=[])
    errors: list[StripeVerificationError] = Field(default=[])


class StripeVerification(BaseModel):
    status: str


class StripeIndividual(BaseModel):
    requirements: StripeRequirements
    verification: StripeVerification


class StripeUpdateAccountObject(BaseModel):
    id: str
    individual: StripeIndividual


class StripeUpdateAccountEventData(BaseModel):
    object: StripeUpdateAccountObject


def create_custom_unit_amount_params(currency: str) -> Dict[str, Any]:
    minimum_amount = round(convert_usd_to_currency(Config.TRANSFER_MINIMUM_USD, currency) * 100)
    maximum_amount = round(convert_usd_to_currency(Config.TRANSFER_MAXIMUM_USD, currency) * 100)
    return {
        'enabled': True,
        'minimum': minimum_amount,
        'maximum': maximum_amount,
    }


def create_price_params(description: str, currency: str) -> Dict[str, Any]:
    return {
        'product_data': {
            'name': description,
        },
        'currency': currency.lower(),
        'custom_unit_amount': create_custom_unit_amount_params(currency),
        'tax_behavior': 'inclusive',
    }


@dataclass(frozen=False)
class StripeAccount:
    account_id: str
    creator_id: uuid.UUID
    verification_status: str
    verification_details: StripeRequirements | None
    removed: bool
    last_event_time: datetime.datetime | None

    @staticmethod
    def _prepare_personal_info(personal_info: dict, website_url: str) -> Dict[str, Any]:
        phone = personal_info.get("phone", None)

        full_name_aliases = personal_info.get("full_name_aliases", [""])
        if full_name_aliases is not None and len(full_name_aliases) == 0:
            personal_info["full_name_aliases"] = [""]

        nationality = personal_info.get("nationality", None)
        if nationality:
            personal_info["nationality"] = country_codes.get(nationality)

        data = {
            "company": {
                "phone": phone,
            },
            "capabilities": {
                "card_payments": {"requested": True},
                "transfers": {"requested": True},
            },
            "business_type": "individual",
            "individual": personal_info,
            "business_profile": {
                "mcc": 5969,  # Digital marketing - other
                "url": website_url
            }
        }

        return data

    @staticmethod
    def create_new(
            creator_id: uuid.UUID,
            website_url: str,
            country: str,
            personal_info: dict,
            cur: cursor
    ) -> 'StripeAccount':
        data = StripeAccount._prepare_personal_info(personal_info, website_url)
        country_code = country_codes.get(country)

        data["type"] = "custom"
        data["country"] = country_code
        response = stripe.Account.create(api_key=Config.STRIPE_USER, **data)
        account_id = response["id"]
        logger.info(f"New stripe account created {account_id}")
        cur.execute(
            f"INSERT INTO public.stripe_account(stripe_account, creator_id, verification_status, last_event_time) "
            f"VALUES (%s, %s, 'verifying', (now() AT TIME ZONE 'utc'));",
            (account_id, creator_id,)
        )
        logger.info(f"Stripe account {account_id} linked to creator {creator_id}")
        return StripeAccount(
            account_id=account_id, creator_id=creator_id, removed=False,
            verification_status="verifying", verification_details=None,
            last_event_time=datetime.datetime.utcnow(),
        )

    @staticmethod
    def get_account_by_creator_id(creator_id: uuid.UUID, cur: cursor) -> 'StripeAccount | None':
        cur.execute(
            f"SELECT stripe_account, verification_status, verification_details, last_event_time "
            f"FROM public.stripe_account "
            f"WHERE creator_id=%s AND removed = False;",
            (creator_id,)
        )
        result = cur.fetchone()
        if result is None:
            return None

        verification_details = StripeRequirements.model_validate_json(result[2]) if result[2] else None
        return StripeAccount(
            account_id=result[0], creator_id=creator_id, removed=False,
            verification_status=result[1], verification_details=verification_details,
            last_event_time=result[3],
        )

    @staticmethod
    def load(account_id: str, cur: cursor) -> 'StripeAccount | None':
        cur.execute(
            f"SELECT "
            f"stripe_account, creator_id, verification_status, "
            f"verification_details, removed, last_event_time "
            f"FROM public.stripe_account "
            f"WHERE stripe_account = %s;",
            (account_id,)
        )

        result = cur.fetchone()
        if result is None:
            return None

        verification_details = StripeRequirements.model_validate_json(result[3]) if result[3] else None
        return StripeAccount(
            account_id=result[0], creator_id=result[1], verification_status=result[2],
            verification_details=verification_details, removed=result[4], last_event_time=result[5]
        )

    def update(self, personal_info: dict, website_url: str, cur: cursor) -> None:
        data = StripeAccount._prepare_personal_info(personal_info, website_url)
        stripe.Account.modify(id=self.account_id, api_key=Config.STRIPE_USER, **data)
        logger.info(f"Stripe account {self.account_id} updated")
        cur.execute(
            "UPDATE public.stripe_account SET "
            "verification_status = 'verifying', "
            "verification_details = NULL, "
            "last_event_time = (now() AT TIME ZONE 'utc') "
            "WHERE stripe_account = %s;",
            (self.account_id,)
        )

    def create_verification_link(self, access_token: str) -> str:
        response = stripe.AccountLink.create(
            api_key=Config.STRIPE_USER,
            account=self.account_id,
            refresh_url=f"{Config.USER_UI_BASE}/stripe_refresh?access_token={access_token}",
            return_url=f"{Config.USER_UI_BASE}/dashboard?access_token={access_token}",
            type="account_onboarding",
        )
        logger.info(f"Account link: {response}")
        return response["url"]

    def set_verification_status(
            self,
            verified: bool,
            details: StripeRequirements,
            event_time: datetime.datetime,
            cur: cursor
    ) -> None:
        if (
                verified == (self.verification_status == "verified")
                and details == self.verification_details
        ):
            return

        if verified:
            verification_status = "verified"

        elif len(details.pending_verification) > 0:
            verification_status = "verifying"

        elif len(details.errors) > 0:
            if any([
                error.requirement == "verification.document"
                or error.requirement == "verification.proof_of_liveness"
                for error in details.errors
            ]):
                verification_status = "verification-external"
                details=StripeRequirements(eventually_due=["continue in Stripe"])
            else:
                verification_status = "verification-error"

        elif len(details.eventually_due) > 0:
            if any([
                entry == "verification.document"
                or entry == "verification.proof_of_liveness"
                for entry in details.eventually_due
            ]):
                verification_status = "verification-external"
            else:
                verification_status = "information-required"

        else:
            verification_status = "verifying"

        logger.debug(f"Stripe account {self.account_id} verification status: {verification_status}")
        cur.execute(
            "UPDATE public.stripe_account "
            f"SET verification_status = %s, verification_details = %s, last_event_time = %s "
            f"WHERE stripe_account=%s AND removed=False;",
            (verification_status, details.model_dump_json(), event_time, self.account_id,)
        )

    @staticmethod
    def remove_for_creator(creator_id: uuid.UUID, cur: cursor) -> None:
        cur.execute(
            "SELECT stripe_account FROM public.stripe_account "
            "WHERE creator_id = %s AND removed = False;",
            (creator_id,)
        )

        entry = cur.fetchone()
        if entry is not None:
            stripe_acc = stripe.Account.retrieve(api_key=Config.STRIPE_USER, id=entry[0])
            stripe_acc.delete()

            cur.execute(
                f"UPDATE public.stripe_account "
                f"SET removed = True "
                f"WHERE creator_id = %s AND removed = False;",
                (creator_id,)
            )

    @staticmethod
    def get_price(
            stripe_account: str,
            creator_id: uuid.UUID,
            currency: str,
            description: str,
            cur: cursor
    ) -> str:
        cur.execute(
            "SELECT price_id FROM public.stripe_price "
            "WHERE stripe_account = %s AND creator_id = %s AND currency = %s;",
            (stripe_account, creator_id, currency.upper())
        )

        entry = cur.fetchone()
        if entry is not None:
            return entry[0]

        price_params = create_price_params(description, currency)
        price = stripe.Price.create(api_key=Config.STRIPE_USER, stripe_account=stripe_account, **price_params)
        cur.execute(
            "INSERT INTO public.stripe_price(stripe_account, creator_id, currency, price_id) "
            "VALUES(%s, %s, %s, %s);",
            (stripe_account, creator_id, currency.upper(), price.id)
        )

        return price.id
