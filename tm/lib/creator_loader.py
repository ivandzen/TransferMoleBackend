import logging

from psycopg2.extensions import cursor
import uuid
import datetime
import json
from typing import Optional, ClassVar

from .common.api_error import APIError
from .creator import Creator
from .country_cache import CountryCache


class CreatorLoader:
    STRANGER: ClassVar[Optional[Creator]] = None

    @staticmethod
    def create_new(cur: cursor) -> Creator:
        logging.info(f"Creating new user...")
        reg_datetime = datetime.datetime.utcnow()
        cur.execute(f"INSERT INTO public.creator(reg_datetime) "
                    f"VALUES(%s) "
                    f"RETURNING creator_id;",
                    (reg_datetime,))
        result = cur.fetchone()
        if result is None:
            raise APIError(APIError.INTERNAL, "Failed to create user")

        new_creator = Creator(
            creator_id=result[0],
            reg_datetime=reg_datetime,
            country=None,
            personal_info=None,
            removed=False,
        )
        return new_creator

    @staticmethod
    def restore_creator(creator_id: uuid.UUID, cur: cursor) -> Creator:
        logging.info(f"Creator {creator_id} will be restored...")
        reg_datetime = datetime.datetime.utcnow()
        cur.execute(
            f"UPDATE public.creator "
            f"SET removed = False AND reg_datetime = %s "
            f"WHERE creator_id = %s "
            f"RETURNING country, personal_info;",
            (reg_datetime, creator_id,)
        )

        result = cur.fetchone()
        if result is None:
            raise APIError(APIError.INTERNAL, "Unable to restore user")

        personal_info = json.loads(result[1]) if result[1] is not None else None
        country = CountryCache.get_country(result[0]) if result[0] else None
        return Creator(
            creator_id=creator_id,
            reg_datetime=reg_datetime,
            country=country,
            personal_info=personal_info,
            removed=False,
        )

    @staticmethod
    def get_creator_by_id(creator_id: uuid.UUID | None, cur: cursor, with_removed: bool = False) -> Creator | None:
        if not creator_id:
            return None

        query = (
            f"SELECT "
            f"      c.creator_id, "
            f"      c.reg_datetime, "
            f"      c.country, "
            f"      c.personal_info, "
            f"      c.removed "
            f"FROM public.creator AS c "
            f"WHERE c.creator_id = '{creator_id}'"
        )

        if with_removed:
            query += ";"
        else:
            query += " AND c.removed = False;"

        cur.execute(query)
        result = cur.fetchone()
        if result is None:
            return None

        personal_info = json.loads(result[3]) if result[3] is not None else None
        country = CountryCache.get_country(result[2]) if result[2] else None
        return Creator(
            creator_id=result[0],
            reg_datetime=result[1],
            country=country,
            personal_info=personal_info,
            removed=result[4],
        )

    @classmethod
    def get_stranger(cls, cur: cursor) -> Creator:
        if not cls.STRANGER:
            cls.STRANGER = CreatorLoader.get_creator_by_id(uuid.UUID(int=0), cur)
            if not cls.STRANGER:
                logging.warning(f"Stranger user not found")
                raise APIError(APIError.INSTAGRAM_ERROR, "Unexpected error. Please, contact customer support")

        return cls.STRANGER
