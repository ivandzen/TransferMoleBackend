import logging
import uuid
from typing import List, Optional, Any, Dict
from psycopg2.extensions import cursor
from pydantic import BaseModel, Field, field_serializer
import datetime
import json

from ..common.api_error import APIError
from ..notification import VerificationStarted, VerificationComplete
from ..notification_utils import send_notification
from .kyc_provider import KYCProvider
from ..creator import Creator, VerificationState, VerificationIntent
from ..authentication.auth_account_factory import AuthAccountFactory, AuthAccount


class InternalKYCStep(BaseModel):
    step_index: int
    verification_status: str = Field(pattern="^[A-Za-z0-9\-]+$")
    message: Optional[str] = None
    created: datetime.datetime

    @field_serializer('created')
    def serialize_created(self, created: datetime.datetime, _info: Any) -> int:
        return int(created.timestamp() * 1000)


class InternalKYCHistory(BaseModel):
    creator_id: uuid.UUID
    communication: List[AuthAccount]
    steps: List[InternalKYCStep]

    @staticmethod
    def get(creator_id: uuid.UUID, cur: cursor) -> 'InternalKYCHistory':
        cur.execute(
            "SELECT step_index, verification_status, message, created "
            "FROM public.internal_kyc_history "
            "WHERE creator_id = %s ORDER BY step_index;",
            (creator_id,)
        )

        steps = []
        for entry in cur:
            steps.append(
                InternalKYCStep(
                    step_index=entry[0],
                    verification_status=entry[1],
                    message=entry[2],
                    created=entry[3]
                )
            )

        auth_accounts = AuthAccountFactory.load_creator_accounts(creator_id, cur)
        if len(auth_accounts) == 0:
            raise APIError(APIError.PERSONAL_INFO, "User dont have social accounts linked")

        return InternalKYCHistory(
            creator_id=creator_id,
            communication=auth_accounts,
            steps=steps,
        )

    def new_step(self, verification_status: str, message: str | None, cur: cursor) -> InternalKYCStep:
        cur.execute(
            "INSERT INTO public.internal_kyc_history ("
            "creator_id, step_index, verification_status, message"
            ") "
            "VALUES(%s, %s, %s, %s)"
            "RETURNING step_index, created;",
            (self.creator_id, len(self.steps), verification_status, message,)
        )
        result = cur.fetchone()
        if not result:
            raise APIError(
                APIError.INTERNAL,
                "Unable to create verification step"
            )

        new_step = InternalKYCStep(
            step_index=result[0],
            verification_status=verification_status,
            message=message,
            created=result[1]
        )
        self.steps.append(new_step)
        return new_step


class InternalKYCProvider(KYCProvider):
    def add_verification_step(
            self,
            creator_id: uuid.UUID,
            verification_status: str,
            message: str | None,
            cur: cursor
    ) -> InternalKYCStep:
        history = InternalKYCHistory.get(creator_id, cur)
        if len(history.steps) == 0 or history.steps[-1].verification_status != "verifying":
            raise APIError(
                APIError.INTERNAL,
                "User yet not submitted for verification"
            )

        if verification_status not in ["verification-error", "verified"]:
            raise APIError(
                APIError.INTERNAL,
                f"Verification status {verification_status} is not supported"
            )

        if verification_status == "verified":
            send_notification(creator_id, VerificationComplete(verification_provider="Internal"), None)

        return history.new_step(verification_status=verification_status, message=message, cur=cur)

    def start_verification(
            self,
            creator: Creator,
            access_token: str,
            cur: cursor
    ) -> VerificationIntent | None:
        if creator.personal_info is None:
            raise APIError(APIError.PERSONAL_INFO, "User's personal info not completed")

        history = InternalKYCHistory.get(creator.creator_id, cur)
        if len(history.steps) != 0:
            if history.steps[-1].verification_status == "verifying":
                raise APIError(
                    APIError.INTERNAL,
                    f"We're already verifying your account. Please, wait for results"
                )

            if history.steps[-1].verification_status == "verified":
                raise APIError(
                    APIError.INTERNAL,
                    f"Account already verified"
                )

            if history.steps[-1].verification_status == "removed":
                raise APIError(
                    APIError.INTERNAL,
                    f"Account removed"
                )

        history.new_step(
            verification_status="verifying",
            message=json.dumps(creator.personal_info),
            cur=cur
        )

        send_notification(creator.creator_id, VerificationStarted(verification_provider="Internal"), None)
        return None

    def get_verification_state(
            self,
            creator_id: uuid.UUID,
            cur: cursor
    ) -> VerificationState:
        history = InternalKYCHistory.get(creator_id, cur)
        if len(history.steps) == 0:
            return VerificationState(
                name="unverified",
                description=None
            )

        return VerificationState(
            name=history.steps[-1].verification_status,
            description=history.steps[-1].message
        )

    def remove_verification(self, creator_id: uuid.UUID, cur: cursor) -> None:
        history = InternalKYCHistory.get(creator_id, cur)
        if len(history.steps) != 0:
            if history.steps[-1].verification_status == "removed":
                return

        history.new_step("removed", None, cur)

    def get_pending_verifications(self, cur: cursor) -> list[InternalKYCHistory]:
        cur.execute(
            "WITH latest_statuses AS ("
            "   SELECT DISTINCT ON (ikh2.creator_id) ikh2.creator_id, ikh2.verification_status "
            "   FROM public.internal_kyc_history AS ikh2 "
            "   ORDER BY ikh2.creator_id, ikh2.step_index DESC "
            ") SELECT ikh1.creator_id, ikh1.step_index, ikh1.verification_status, ikh1.message, ikh1.created "
            "FROM public.internal_kyc_history AS ikh1 "
            "   INNER JOIN latest_statuses AS ls "
            "   ON ikh1.creator_id = ls.creator_id "
            "WHERE "
            "   ls.verification_status = 'verifying' "
            "ORDER BY ikh1.step_index;"
        )

        entries = []
        for entry in cur:
            entries.append(entry)

        result: Dict[uuid.UUID, InternalKYCHistory] = {}
        for entry in entries:
            kyc_history = result.get(entry[0], None)
            if not kyc_history:
                auth_accounts = AuthAccountFactory.load_creator_accounts(entry[0], cur)
                if len(auth_accounts) == 0:
                    continue

                result[entry[0]] = InternalKYCHistory(
                    creator_id=entry[0],
                    communication=auth_accounts,
                    steps=[]
                )

            logging.info(f"{entry[1]}   {entry[2]}")
            result[entry[0]].steps.append(
                InternalKYCStep(
                    step_index=entry[1],
                    verification_status=entry[2],
                    message=entry[3],
                    created=entry[4]
                )
            )

        return [entry for _, entry in result.items()]


INTERNAL_KYC_PROVIDER = InternalKYCProvider()
