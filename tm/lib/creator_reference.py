from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional
from psycopg2.extensions import cursor
import uuid

from .common.api_error import APIError
from .authentication.auth_account import SocialReference
from .authentication.auth_account_factory import AuthAccountFactory
from .creator import Creator
from .creator_loader import CreatorLoader


class CreatorReference(BaseModel):
    creator_id: Optional[uuid.UUID] = Field(default=None)
    social: Optional[SocialReference] = Field(default=None)

    @field_validator("creator_id", mode="before")
    @classmethod
    def transform(cls, raw: str | None) -> uuid.UUID | None:
        if not raw:
            return None
        try:
            return uuid.UUID(raw)
        except Exception as _:
            raise APIError(APIError.WRONG_UUID, f"Wrong UUID format")

    @model_validator(mode="after")
    def validate_self(self) -> 'CreatorReference':
        if not self.creator_id and not self.social:
            raise APIError(
                APIError.WRONG_PARAMETERS,
                "Either creator_id or social reference should be set"
            )

        if self.creator_id and self.social:
            raise APIError(
                APIError.WRONG_PARAMETERS,
                "Both creator_id and social defined"
            )

        return self


def load_creator_by_reference(reference: CreatorReference, cur: cursor) -> Creator | None:
    if reference.creator_id:
        return CreatorLoader.get_creator_by_id(reference.creator_id, cur)

    if reference.social:
        if reference.social.username:
            auth_account = AuthAccountFactory.get_by_username(
                reference.social.platform, reference.social.username, cur
            )
            if not auth_account:
                return None

            return CreatorLoader.get_creator_by_id(auth_account.creator_id, cur)
        elif reference.social.userid:
            auth_account = AuthAccountFactory.get_by_userid(
                reference.social.platform, reference.social.userid, cur
            )

            if not auth_account:
                return None

            return CreatorLoader.get_creator_by_id(auth_account.creator_id, cur)

    return None
