from pydantic import BaseModel
import os
import base64
from hashlib import sha256
import logging

from ..common.api_error import APIError
from ..redis_cache import RedisConnection


logger = logging.getLogger(__name__)


class Auth0Session(BaseModel):
    verifier: str
    challenge: str
    state: str

    @staticmethod
    async def create_new() -> 'Auth0Session':
        verifier = os.urandom(32)
        verifier = str(base64.urlsafe_b64encode(verifier), 'utf-8')[:-1]
        hasher = sha256()
        hasher.update(verifier.encode('ascii'))
        challenge = hasher.digest()
        challenge = str(base64.urlsafe_b64encode(challenge), 'utf-8')[:-1]
        state = str(base64.urlsafe_b64encode(os.urandom(32)), 'utf-8')[:-1]
        result = Auth0Session(
            verifier=verifier, challenge=challenge, state=state
        )

        if not RedisConnection.connection.set(f"a0-session:{state}", result.model_dump_json()):
            raise APIError(
                APIError.INTERNAL,
                f"Failed to create session"
            )

        return result

    @staticmethod
    async def get_by_state(state: str) -> 'Auth0Session':
        session = RedisConnection.connection.getdel(f"a0-session:{state}")
        if not session:
            raise APIError(
                APIError.OBJECT_NOT_FOUND, f"Session not found"
            )

        return Auth0Session.model_validate_json(session)
