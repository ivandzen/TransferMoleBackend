import datetime
from dataclasses import dataclass
import logging
import uuid
from psycopg2.extensions import cursor
from pydantic import BaseModel
from typing import Literal, Optional, List

from ..creator import VerificationState

logger = logging.getLogger(__name__)


class ReviewResult(BaseModel):
    reviewAnswer: Literal["RED", "GREEN"]
    rejectLabels: Optional[List[str]] = None
    reviewRejectType: Optional[str] = None


class ReviewStatus(BaseModel):
    reviewId: str
    attemptId: str
    attemptCnt: int
    elapsedSincePendingMs: Optional[int] = None
    elapsedSinceQueuedMs: Optional[int] = None
    reprocessing: Optional[bool] = None
    levelName: str
    createDate: str
    reviewDate: Optional[str] = None
    reviewResult: Optional[ReviewResult] = None
    reviewStatus: Literal["init", "pending", "prechecked", "queued", "completed", "onHold"]
    confirmed: Optional[bool] = None
    priority: int


@dataclass
class SumsubApplicant:
    applicant_id: str
    creator_id: uuid.UUID
    review_status: ReviewStatus
    last_event_time: datetime.datetime

    @staticmethod
    def create_new(
            applicant_id: str,
            creator_id: uuid.UUID,
            review_status: ReviewStatus,
            event_time: datetime.datetime,
            cur: cursor
    ) -> "SumsubApplicant":
        cur.execute(
            "INSERT INTO public.sumsub_applicant (applicant_id, creator_id, review_status, last_event_time)"
            "VALUES (%s, %s, %s, %s);",
            (applicant_id, creator_id, review_status.model_dump_json(), event_time,)
        )

        return SumsubApplicant(
            applicant_id=applicant_id,
            creator_id=creator_id,
            review_status=review_status,
            last_event_time=event_time,
        )

    @staticmethod
    def get_by_id(applicant_id: str, cur: cursor) -> "SumsubApplicant | None":
        cur.execute(
            'SELECT creator_id, review_status, last_event_time '
            'FROM public.sumsub_applicant '
            'WHERE applicant_id = %s AND removed = False;',
            (applicant_id,)
        )

        entry = cur.fetchone()
        if entry is None:
            return None

        return SumsubApplicant(
            applicant_id=applicant_id,
            creator_id=entry[0],
            review_status=ReviewStatus.model_validate_json(entry[1]),
            last_event_time=entry[2]
        )

    @staticmethod
    def get_by_creator_id(creator_id: uuid.UUID, cur: cursor) -> "SumsubApplicant | None":
        cur.execute(
            'SELECT applicant_id, creator_id, review_status, last_event_time '
            'FROM public.sumsub_applicant '
            'WHERE creator_id = %s AND removed = False;',
            (creator_id,)
        )

        entry = cur.fetchone()
        if entry is None:
            return None

        return SumsubApplicant(
            applicant_id=entry[0],
            creator_id=entry[1],
            review_status=ReviewStatus.model_validate_json(entry[2]),
            last_event_time=entry[3]
        )

    def update_review_status(self, review_status: ReviewStatus, event_time: datetime.datetime, cur: cursor) -> None:
        cur.execute(
            'UPDATE public.sumsub_applicant '
            'SET review_status = %s, last_event_time = %s '
            'WHERE applicant_id = %s;',
            (review_status.model_dump_json(), event_time, self.applicant_id,)
        )

    def remove(self, cur: cursor) -> None:
        cur.execute(
            "UPDATE public.sumsub_applicant SET removed = True WHERE applicant_id = %s;",
            (self.applicant_id,)
        )

    def get_verification_state(self) -> VerificationState:
        if self.review_status.reviewStatus == "completed":
            if self.review_status.reviewResult and self.review_status.reviewResult.reviewAnswer == "GREEN":
                return VerificationState(
                    name="verified",
                    description=None,
                )

            return VerificationState(
                name="rejected",
                description="Your verification was rejected. Contact customer support for details",
            )

        if self.review_status.reviewStatus == "init":
            return VerificationState(
                name="verification-external",
                description="Continue verification to buy crypto",
            )

        return VerificationState(
            name="verifying",
            description=None,
        )
