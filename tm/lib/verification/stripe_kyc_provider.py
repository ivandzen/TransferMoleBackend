import uuid
from psycopg2.extensions import cursor

from .stripe_account import StripeAccount
from .kyc_provider import KYCProvider
from ..common.api_error import APIError
from ..creator import Creator, VerificationState, VerificationIntent
from ..authentication.auth_account_factory import AuthAccountFactory
from ..notification import VerificationStarted
from ..notification_utils import send_notification


class StripeKYCProvider(KYCProvider):
    def start_verification(
            self,
            creator: Creator,
            access_token: str,
            cur: cursor
    ) -> VerificationIntent | None:
        if creator.personal_info is None:
            raise APIError(APIError.PERSONAL_INFO, "User's personal info not completed")

        if creator.country is None:
            raise APIError(APIError.CREATOR_COUNTRY_NOT_SELECTED, "Country not set")

        requirements = creator.country.get_individual_requirements()
        requirements.check(creator.personal_info, soft_mode=False)
        auth_accounts = AuthAccountFactory.load_creator_accounts(creator.creator_id, cur)
        if len(auth_accounts) == 0:
            raise APIError(APIError.PERSONAL_INFO, "User dont have social accounts linked")

        website_url = auth_accounts[0].get_website_url()
        stripe_account = StripeAccount.get_account_by_creator_id(creator.creator_id, cur)
        if stripe_account is None:
            StripeAccount.create_new(
                creator_id=creator.creator_id,
                website_url=website_url,
                country=creator.country.name,
                personal_info=creator.personal_info,
                cur=cur
            )
            send_notification(
                creator.creator_id,
                VerificationStarted(verification_provider="Stripe"),
                None,
            )
            return None
        else:
            if stripe_account.verification_status == "verification-external":
                # TODO should be one-shot access-token
                return VerificationIntent(redirect_url=stripe_account.create_verification_link(access_token))
            if stripe_account.verification_status == "verified":
                raise APIError(APIError.INTERNAL)
            if stripe_account.verification_status == "verifying":
                raise APIError(APIError.INTERNAL)
            stripe_account.update(creator.personal_info, website_url=website_url, cur=cur)
            return None

    def get_verification_state(
            self,
            creator_id: uuid.UUID,
            cur: cursor
    ) -> VerificationState:
        stripe_account = StripeAccount.get_account_by_creator_id(creator_id, cur)
        if stripe_account is None:
            return VerificationState(
                name="unverified",
                description=None,
            )

        description = None
        if stripe_account.verification_details:
            if stripe_account.verification_details.eventually_due:
                description = f"Information required: {stripe_account.verification_details.eventually_due}"

        return VerificationState(
            name=stripe_account.verification_status,
            description=description
        )

    def remove_verification(self, creator_id: uuid.UUID, cur: cursor) -> None:
        StripeAccount.remove_for_creator(creator_id, cur)
