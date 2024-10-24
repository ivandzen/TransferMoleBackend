import logging

from psycopg2.extensions import cursor

from ..common.api_error import APIError
from ..creator import Creator, VerificationIntent, VerificationStates
from . import KYC_PROVIDERS


class CreatorVerificator:
    @staticmethod
    def get_verification_states(creator: Creator, cur: cursor) -> VerificationStates:
        verification_states = {}
        if creator.country:
            for kyc_provider_name in creator.country.kyc_providers:
                kyc_provider = KYC_PROVIDERS.get(kyc_provider_name, None)
                if not kyc_provider:
                    logging.error(f"Unexpected KYC Provider {kyc_provider_name} for creator {creator.creator_id}")
                    raise APIError(
                        APIError.INTERNAL,
                        f"Unexpected error. Please, contact customer support"
                    )

                verification_states[kyc_provider_name] = kyc_provider.get_verification_state(creator.creator_id, cur)

        return VerificationStates(verification_states)

    @staticmethod
    def start_verification(
            creator: Creator,
            kyc_provider_name: str,
            access_token: str,
            cur: cursor
    ) -> VerificationIntent | None:
        if not creator.country:
            raise APIError(APIError.INSTAGRAM_ERROR, f"Verification is not available - country not set")

        if kyc_provider_name not in creator.country.kyc_providers:
            raise APIError(
                APIError.INSTAGRAM_ERROR,
                f"KYC Provider {kyc_provider_name} is not supported in country {creator.country.name}"
            )

        kyc_provider = KYC_PROVIDERS.get(kyc_provider_name, None)
        if not kyc_provider:
            logging.error(f"KYC provider {kyc_provider} does not exist")
            raise APIError(APIError.INTERNAL, f"Unexpected error. Please, contact customer support")

        return kyc_provider.start_verification(creator, access_token, cur)

    @staticmethod
    def remove_verifications(creator: Creator, cur: cursor) -> None:
        if not creator.country:
            return

        for kyc_provider_name in creator.country.kyc_providers:
            kyc_provider = KYC_PROVIDERS.get(kyc_provider_name, None)
            if not kyc_provider:
                logging.error(f"Unknown KYCProvider {kyc_provider_name} for creator {creator.creator_id}")
                continue

            kyc_provider.remove_verification(creator.creator_id, cur)
