import uuid
import logging
from decimal import Decimal
from typing import Optional, List
from psycopg2.extensions import cursor
from pydantic import BaseModel, Field

from .payment_intent import PaymentIntent
from ..creator import Creator
from ..payout.providers.payout_provider import PayoutProvider

logger = logging.getLogger(__name__)


class ProviderAccount(BaseModel):
    provider: PayoutProvider
    supported_payment_types: List[str]
    external_id: Optional[str] = Field(default=None, exclude=True)

    def validate_existing_transaction(self, amount: Decimal, external_id: str) -> None:
        raise NotImplementedError(__name__)

    def remove(self, cur: cursor) -> None:
        pass

    def receive_payment(
            self,
            payment_type: str,
            recipient: Creator,
            transfer_id: uuid.UUID,
            amount: Decimal | None,
            collect_fee: bool,
            cur: cursor,
    ) -> PaymentIntent:
        raise NotImplementedError(__name__)


def try_restore_provider_account(
        channel_id: uuid.UUID,
        provider: str,
        provider_data_serialized: str | None,
        external_id: str | None,
        cur: cursor,
) -> bool:
    cur.execute(
        "UPDATE public.provider_account "
        "SET provider_data = %s, external_id = %s "
        "WHERE channel_id = %s AND provider = %s "
        "RETURNING channel_id;",
        (provider_data_serialized, external_id, channel_id, provider)
    )

    entry = cur.fetchone()
    return entry is not None


def create_new_provider_account(
        channel_id: uuid.UUID,
        provider: str,
        provider_data: BaseModel | None,
        external_id: str | None,
        cur: cursor,
) -> None:
    provider_data_serialized = provider_data.model_dump_json() if provider_data else None
    restored = try_restore_provider_account(
        channel_id=channel_id,
        provider=provider,
        provider_data_serialized=provider_data_serialized,
        external_id=external_id,
        cur=cur
    )

    if restored:
        return

    cur.execute(
        "INSERT INTO public.provider_account ("
        "   channel_id, provider, provider_data, external_id"
        ") "
        "VALUES (%s, %s, %s, %s);",
        (channel_id, provider, provider_data_serialized, external_id)
    )
