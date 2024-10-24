import logging
import uuid
from datetime import datetime
import requests

from pydantic import BaseModel
from typing_extensions import Dict
from psycopg2.extensions import cursor

from .common.config import Config
from .common.api_error import APIError

logger = logging.getLogger(__name__)
REFERRAL_POINTS = 300
REFERREE_POINTS = 2500

class Points(BaseModel):
    amount: int
    at: datetime


class CreatorPoints(BaseModel):
    creator_id: uuid.UUID
    points: Dict[str, Points]

    def season1_migrated(self) -> bool:
        return "season1" in self.points

    def total_points(self) -> int:
        result = 0
        for _, points in self.points.items():
            result += points.amount
        return result


def load_creator_points(creator_id: uuid.UUID, tg_userid: str | None, cur: cursor) -> CreatorPoints:
    cur.execute(
        "SELECT task_name, points, at FROM public.creator_points WHERE creator_id = %s;",
        (creator_id,)
    )

    points = CreatorPoints(
        creator_id=creator_id,
        points={entry[0]: Points(amount=entry[1], at=entry[2]) for entry in cur},
    )

    if not points.season1_migrated() and tg_userid is not None:
        response = requests.post(
            url=Config.MAKE_USER_GAME_STATUS,
            json={
                "TelegramID": tg_userid
            }
        )

        if response.status_code != 200:
            logger.error(f"Failed to get balance for user {tg_userid}")
            raise APIError(APIError.INTERNAL, "Failed to get user balance")

        season1_points = int(response.json().get("Balance", 0))
        points.points["season1"] = task_completed(creator_id, "season1", season1_points, cur)

    return points


def task_completed(creator_id: uuid.UUID, task_name: str, points: int, cur: cursor) -> Points:
    cur.execute(
        "INSERT INTO public.creator_points (creator_id, task_name, points)"
        "VALUES (%s, %s, %s) "
        "RETURNING at;",
        (creator_id, task_name, points,)
    )

    entry = cur.fetchone()
    if not entry:
        logger.error(f"Failed to add {task_name} {points} points for creator {creator_id}")
        raise APIError(APIError.INTERNAL, "Unexpected error. Please, contact customer support")

    return Points(amount=points, at=entry[0])


def add_creator_points(creator_id: uuid.UUID, task_name: str, add_points: int, cur: cursor) -> int:
    cur.execute(
        "INSERT INTO public.creator_points (creator_id, task_name, points, at) "
        "VALUES (%s, %s, %s, now() at time zone 'utc') "
        "ON CONFLICT (creator_id, task_name) "
        "DO UPDATE SET points = creator_points.points + %s, at = excluded.at "
        "RETURNING points;",
        (creator_id, task_name, add_points, add_points)
    )

    entry = cur.fetchone()
    if not entry:
        return 0

    return entry[0]
