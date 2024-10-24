import logging
import hmac
import hashlib
from fastapi import APIRouter, Depends
from fastapi.requests import Request
from typing import Annotated
from psycopg2.extensions import cursor

from .common import database_cursor
from ..common.api_error import APIError
from ..common.config import Config
from ..verification.sumsub_applicant import SumsubApplicant
from ..verification.sumsub_kyc_provider import WebhookPayload, WebhookContext
from ..verification import SUMSUB_KYC_PROVIDER


logger = logging.getLogger(__name__)
router = APIRouter(prefix=f"/sumsub", tags=["sumsub_webhook"])


async def check_webhook(request: Request) -> WebhookPayload:
    digest_alg = request.headers.get("X-Payload-Digest-Alg")
    match digest_alg:
        case "HMAC_SHA1_HEX":
            digest_func = hashlib.sha1
        case "HMAC_SHA256_HEX":
            digest_func = hashlib.sha256
        case "HMAC_SHA512_HEX":
            digest_func = hashlib.sha512
        case unknown:
            raise APIError(APIError.INTERNAL, f"Unable to process webhook with digest alg: {unknown}")

    expected_digest = hmac.new(
        Config.SUMSUB_WEBHOOK_SECRET_KEY.encode('utf-8'),
        msg=await request.body(),
        digestmod=digest_func,
    ).hexdigest()

    actual_digest = request.headers.get("X-Payload-Digest")
    if actual_digest != expected_digest:
        raise APIError(APIError.INTERNAL, f"Webhook signature not correct")

    return WebhookPayload.model_validate(await request.json())


async def prepare_webhook_context(
        webhook_payload: Annotated[WebhookPayload, Depends(check_webhook)],
        cur: Annotated[cursor, Depends(database_cursor)],
) -> WebhookContext:
    logger.info(f"Webhook event received {webhook_payload}")
    return WebhookContext(
        payload=webhook_payload,
        applicant=SumsubApplicant.get_by_id(webhook_payload.applicantId, cur),
        cur=cur
    )


@router.post(path="/")
async def post_hook(context: Annotated[WebhookContext, Depends(prepare_webhook_context)]) -> None:
    SUMSUB_KYC_PROVIDER.process_webhook(context)
