from psycopg2.extensions import cursor
from pydantic import BaseModel
from typing import Literal, Optional, Tuple
from dataclasses import dataclass
import uuid
import time
import hashlib
import hmac
import json
import requests
import logging
import datetime

from ..notification import VerificationStarted
from ..notification_utils import send_notification
from ..common.config import Config
from .kyc_provider import KYCProvider
from ..creator import Creator, VerificationState, VerificationIntent
from ..common.api_error import APIError
from .sumsub_applicant import SumsubApplicant, ReviewResult, ReviewStatus

session = requests.Session()
logger = logging.getLogger(__name__)


def prepare_sumsub_api_params(method: str, url_path: str, json_body: dict | None = None) -> Tuple[int, str, str | None]:
    timestamp = int(time.time())
    sign_source = f"{timestamp}{method}/{url_path}"
    if json_body:
        body = json.dumps(json_body)
        sign_source += body
    else:
        body = None

    signature = hmac.new(
        Config.SUMSUB_APP_SECRET_KEY.encode('utf-8'),
        msg=sign_source.encode('utf-8'),
        digestmod=hashlib.sha256,
    ).hexdigest()

    return timestamp, signature, body


def post_authorized_sumsub_request(url_path: str, json_body: dict | None = None) -> requests.Response:
    timestamp, signature, body = prepare_sumsub_api_params("POST", url_path, json_body)
    if body:
        return session.post(
            url=f"https://api.sumsub.com/{url_path}",
            headers={
                "X-App-Token": Config.SUMSUB_APP_TOKEN,
                "X-App-Access-Ts": str(timestamp),
                "X-App-Access-Sig": signature,
                "content-type": "application/json",
            },
            data=body
        )

    return session.post(
        url=f"https://api.sumsub.com/{url_path}",
        headers={
            "X-App-Token": Config.SUMSUB_APP_TOKEN,
            "X-App-Access-Ts": str(timestamp),
            "X-App-Access-Sig": signature,
        },
    )


def get_authorized_sumsub_request(url_path: str) -> requests.Response:
    timestamp, signature, _ = prepare_sumsub_api_params("GET", url_path, None)
    return session.get(
        url=f"https://api.sumsub.com/{url_path}",
        headers={
            "X-App-Token": Config.SUMSUB_APP_TOKEN,
            "X-App-Access-Ts": str(timestamp),
            "X-App-Access-Sig": signature,
        },
    )


class WebhookPayload(BaseModel):
    applicantId: str
    inspectionId: str
    applicantType: Optional[Literal["individual", "company"]] = None
    correlationId: Optional[str] = None
    levelName: str
    sandboxMode: Optional[bool] = None
    externalUserId: uuid.UUID
    type: Literal[
        "applicantCreated",
        "applicantPending",
        "applicantReviewed",
        "applicantOnHold",
        "applicantActionPending",
        "applicantActionReviewed",
        "applicantActionOnHold",
        "applicantPersonalInfoChanged",
        "applicantTagsChanged",
        "applicantActivated",
        "applicantDeactivated",
        "applicantDeleted",
        "applicantReset",
        "applicantLevelChanged",
        "applicantWorkflowCompleted"
    ]
    reviewResult: Optional[ReviewResult] = None
    reviewStatus: Literal["init", "pending", "completed", "onHold"]
    createdAtMs: datetime.datetime
    clientId: Optional[str] = None


@dataclass
class WebhookContext:
    payload: WebhookPayload
    cur: cursor
    applicant: Optional[SumsubApplicant] = None


class AccessTokenResult(BaseModel):
    token: str
    userId: str


class ShareTokenResult(BaseModel):
    token: str
    forClientId: str


def get_applicant_review_status(applicant_id: str) -> ReviewStatus:
    response = get_authorized_sumsub_request(f"resources/applicants/{applicant_id}/status")
    if response.status_code != 200:
        raise APIError(
            APIError.INTERNAL, f"Failed to get review status for {applicant_id}: {response.content}"
        )

    return ReviewStatus.model_validate(response.json())


class SumsubKYCProvider(KYCProvider):
    def start_verification(
            self,
            creator: Creator,
            access_token: str,
            cur: cursor
    ) -> VerificationIntent | None:
        response = post_authorized_sumsub_request(
            url_path=f"resources/accessTokens?userId={creator.creator_id}&levelName={Config.SUMSUB_KYC_LEVEL}&ttlInSecs=600"
        )

        if response.status_code != 200:
            logger.warning(response.content)
            raise APIError(APIError.INTERNAL, f"Failed to generate Sumsub access token")

        result = AccessTokenResult.model_validate(response.json())
        return VerificationIntent(sumsub_token=result.token)

    def get_verification_state(
            self,
            creator_id: uuid.UUID,
            cur: cursor
    ) -> VerificationState:
        sumsub_applicant = SumsubApplicant.get_by_creator_id(creator_id, cur)
        if sumsub_applicant is None:
            return VerificationState(
                name="unverified",
                description=None,
            )

        return sumsub_applicant.get_verification_state()

    def remove_verification(self, creator_id: uuid.UUID, cur: cursor) -> None:
        pass

    def process_webhook(self, context: WebhookContext) -> None:
        if context.payload.type == "applicantCreated":
            if context.applicant:
                logger.warning(
                    f"applicantCreated webhook received, "
                    f"but user with applicantId {context.applicant.applicant_id} is already in DB"
                )
                raise APIError(APIError.INTERNAL, "Unexpected error")

            SumsubApplicant.create_new(
                applicant_id=context.payload.applicantId,
                creator_id=context.payload.externalUserId,
                review_status=get_applicant_review_status(context.payload.applicantId),
                event_time=context.payload.createdAtMs,
                cur=context.cur
            )

            send_notification(
                context.payload.externalUserId,
                VerificationStarted(verification_provider="Subsub"),
                None,
            )

        elif context.payload.type == "applicantDeleted":
            if not context.applicant:
                logger.warning(f"applicantDeleted webhook received, but applicant field is absent in it")
                raise APIError(APIError.INTERNAL, "Unexpected error")

            context.applicant.remove(context.cur)
        else:
            if not context.applicant:
                logger.warning(f"{context.payload.type} webhook received, but applicant field is absent in it")
                raise APIError(APIError.INTERNAL, "Unexpected error")

            if context.applicant.last_event_time > context.payload.createdAtMs:
                logger.warning(
                    f"Will not update applicant {context.applicant.applicant_id} status because"
                    f"there's already older event written in DB"
                )
                return

            context.applicant.update_review_status(
                review_status=get_applicant_review_status(context.applicant.applicant_id),
                event_time=context.payload.createdAtMs,
                cur=context.cur
            )

    def generate_share_token(self, creator: Creator, client_id: str, cur: cursor) -> ShareTokenResult:
        sumsub_applicant = SumsubApplicant.get_by_creator_id(creator.creator_id, cur)
        if not sumsub_applicant:
            logger.warning(f"Sumsub applicant does not exist for creator {creator.creator_id}")
            raise APIError(
                APIError.INTERNAL,
                f"User is not ready for on-ramp payments"
            )

        verification_state = sumsub_applicant.get_verification_state()
        if verification_state.name != "verified":
            raise APIError(
                APIError.INTERNAL,
                f"User is not ready for on-ramp payments"
            )

        response = post_authorized_sumsub_request(
            f"resources/accessTokens/-/shareToken?applicantId={sumsub_applicant.applicant_id}&forClientId={client_id}"
        )

        if response.status_code != 200:
            raise APIError(
                APIError.INTERNAL,
                f"Failed to get share token for {sumsub_applicant.applicant_id}: {response.content}"
            )

        return ShareTokenResult.model_validate(response.json())
