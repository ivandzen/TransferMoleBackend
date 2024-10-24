import logging
import uuid
from psycopg2.extensions import cursor
from pydantic import BaseModel
from typing import Optional, Literal, Annotated

from ..notification import AccountDeleted
from ..notification_utils import send_notification
from ..creator import Creator
from ..common.api_error import APIError

logger = logging.getLogger(__name__)


class PayoutChannel(BaseModel):
    creator_id: uuid.UUID
    channel_id: uuid.UUID
    currency: Optional[str]
    channel_type: Annotated[str, Literal["crypto", "bank_account"]]
    removed: bool

    def remove(self, cur: cursor) -> None:
        cur.execute(
            f"UPDATE public.payout_channel "
            f"SET removed=True "
            f"WHERE channel_id=%s AND removed=False;",
            (self.channel_id,)
        )

    @staticmethod
    def remove_all_for_creator(creator_id: uuid.UUID, cur: cursor) -> None:
        cur.execute(
            f"UPDATE public.payout_channel "
            f"SET removed = True "
            f"WHERE creator_id = %s AND removed = False "
            f"RETURNING channel_id, type;",
            (creator_id,)
        )

        removed = [(entry[0], entry[1]) for entry in cur]
        for entry in removed:
            send_notification(creator_id, AccountDeleted(channel_id=entry[0], type=entry[1]), None)


def try_restore_payout_channel(
        creator: Creator,
        channel_type: str,
        data_serialized: str,
        currency: str | None,
        cur: cursor
) -> uuid.UUID | None:
    cur.execute(
        "UPDATE public.payout_channel SET removed = False, currency = %s "
        "WHERE creator_id = %s AND type = %s AND data = %s "
        "RETURNING channel_id;",
        (currency, creator.creator_id, channel_type, data_serialized,)
    )
    entry = cur.fetchone()
    if entry is None:
        return None

    return entry[0]


def create_payout_channel(
        creator: Creator,
        channel_type: str,
        data: BaseModel,
        currency: str | None,
        cur: cursor,
) -> uuid.UUID:
    data_serialized = data.model_dump_json()
    channel_id = try_restore_payout_channel(
        creator, channel_type, data_serialized, currency, cur
    )
    if channel_id:
        logger.info(f"Payout channel {channel_id} restored")
        return channel_id
    else:
        cur.execute(
            f"INSERT INTO public.payout_channel(creator_id, type, data, currency) "
            f"VALUES(%s, %s, %s, %s) "
            f"ON CONFLICT ON CONSTRAINT payout_channel_creator_id_type_data_currency_key DO NOTHING "
            f"RETURNING channel_id;",
            (creator.creator_id, channel_type, data_serialized, currency)
        )

        result = cur.fetchone()
        if result is None:
            logger.error(f"Unable to create termination account - the account with the same data already exists")
            raise APIError(APIError.INTERNAL)

        return result[0]
