import uuid
from psycopg2.extensions import cursor

from ..common.api_error import APIError
from ..creator import Creator, VerificationState, VerificationIntent


class KYCProvider:
    def start_verification(
            self,
            creator: Creator,
            access_token: str,
            cur: cursor
    ) -> VerificationIntent | None:
        if creator.country is None:
            raise APIError(APIError.INTERNAL, "Country not set for user")

        raise APIError(
            APIError.INTERNAL,
            f"KYC is not available for {creator.country.name}"
        )

    def get_verification_state(
            self,
            creator_id: uuid.UUID,
            cur: cursor
    ) -> VerificationState:
        return VerificationState(
            name="unverified",
            description=None,
        )

    def remove_verification(self, creator_id: uuid.UUID, cur: cursor) -> None:
        pass
