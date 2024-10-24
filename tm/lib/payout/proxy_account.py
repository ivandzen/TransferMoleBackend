import uuid
import logging
from psycopg2.extensions import cursor
from typing import List, Dict

from .payout_channel import PayoutChannel


logger = logging.getLogger(__name__)


class ProxyAccount:
    @staticmethod
    def get_creator_proxy_rules(creator_id: uuid.UUID, cur: cursor) -> Dict[str, List[uuid.UUID]]:
        """
        :param creator_id: ID of the creator
        :param cur: database cursor
        :return: Mapping: country -> termination account(s)
        """
        cur.execute(
            f"SELECT "
            f"px.country, pc.channel_id "
            f"FROM public.proxy_account AS px "
            f"INNER JOIN public.payout_channel AS pc "
            f"ON px.payout_channel_id = pc.channel_id "
            f"WHERE pc.creator_id = %s AND pc.removed = False;",
            (creator_id,)
        )

        result: Dict[str, list[uuid.UUID]] = {}
        for entry in cur:
            result.setdefault(entry[0], []).append(entry[1])
        return result

    @staticmethod
    def add_proxy_rule(country: str, channel: PayoutChannel, cur: cursor) -> None:
        cur.execute(
            f"INSERT INTO public.proxy_account(country, payout_channel_id) "
            f"VALUES(%s, %s) "
            f"ON CONFLICT (country, payout_channel_id) DO NOTHING;",
            (country, channel.channel_id,)
        )

    @staticmethod
    def remove_proxy_rule(country: str, channel: PayoutChannel, cur: cursor) -> None:
        cur.execute(
            f"DELETE FROM public.proxy_account "
            f"WHERE country = %s AND payout_channel_id = %s;",
            (country, channel.channel_id,)
        )
