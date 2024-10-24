import uuid
from fastapi import APIRouter, Depends
from random import choices, choice
from typing import Annotated, Optional
from pydantic import BaseModel, Field
import logging
from enum import Enum
from psycopg2.extensions import cursor

from ..authentication.auth_account import AuthAccount
from ..common.api_error import APIError
from .common import Context, required_access_token_ctx
from ..creator import Creator
from ..creator_points import load_creator_points
from ..game_tasks import Season2Result
from ..game_notifications import GameNotifications

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/whack-a-mole", tags=["whack-a-mole"])

########################################################################################################################
# Game objects

class MoleType(str, Enum):
    normal = 'normal'
    mega = 'mega'


class GameResult(BaseModel):
    reward: int | None
    mole_type: MoleType
    correct_hole: int


class Game(BaseModel):
    creator_id: uuid.UUID
    remaining_games: int
    mega_mole_probability: float = Field(ge=0.0, le=0.5)
    normal_mole_reward: int = Field(gt=0)
    mega_mole_reward: int = Field(gt=0)
    num_holes: int = Field(gt=0)
    game_result: Optional[GameResult]

    def pick_a_hole(self, hole_idx: int) -> None:
        normal_mole_probability = 1.0 - self.mega_mole_probability
        mole_type = choices(
            [MoleType.normal, MoleType.mega],
            [normal_mole_probability, self.mega_mole_probability]
        )[0]
        reward_size = self.mega_mole_reward if mole_type == 'mega' else self.normal_mole_reward
        correct_hole = choice(range(self.num_holes))
        self.game_result = GameResult(
            reward=reward_size if correct_hole == hole_idx else None,
            mole_type=mole_type,
            correct_hole=correct_hole,
        )
        self.remaining_games -= 1


def check_creator(creator: Creator | None, auth_account: AuthAccount) -> Creator:
    if not creator:
        raise APIError(APIError.OBJECT_NOT_FOUND, "You should register using telegram")

    if auth_account.platform != "tg":
        raise APIError(APIError.INTERNAL, "Whack-a-mole game is available for telegram users only.")

    return creator


def load_game(creator: Creator | None, auth_account: AuthAccount, cur: cursor) -> Game:
    creator = check_creator(creator, auth_account)
    cur.execute(
        "SELECT "
        "   wm.num_games_per_day - COUNT(n.creator_id) as remaining_games, "
        "   wm.mega_mole_probability, wm.normal_mole_reward, wm.mega_mole_reward, wm.num_holes "
        "FROM public.whack_a_mole_2 AS wm "
        "LEFT JOIN public.notification AS n "
        "   ON wm.creator_id=%s "
        "   AND n.creator_id = wm.creator_id "
        "   AND n.category = 'task completed' "
        "   AND n.subcategory = 'season2' "
        "   AND n.created_at >= (NOW() at time zone 'utc') - INTERVAL '1 day' "
        "WHERE wm.creator_id = %s "
        "GROUP BY wm.creator_id;",
        (creator.creator_id, creator.creator_id,)
    )

    entry = cur.fetchone()
    if entry is None:
        cur.execute(
            "INSERT INTO public.whack_a_mole_2 (creator_id) VALUES (%s) "
            "RETURNING num_games_per_day, mega_mole_probability, normal_mole_reward, mega_mole_reward, num_holes;",
            (creator.creator_id,)
        )
        entry = cur.fetchone()

    if entry is None:
        logger.error(f"Unable to create Whack-a-mole record for a user {creator.creator_id}")
        raise APIError(APIError.INTERNAL, "Unexpected error. Please, contact customer support")

    return Game(
        creator_id=creator.creator_id,
        remaining_games=entry[0],
        mega_mole_probability=entry[1],
        normal_mole_reward=entry[2],
        mega_mole_reward=entry[3],
        num_holes=entry[4],
        game_result=None,
    )

########################################################################################################################
# API methods

@router.get(
    path="/start",
    response_model=Game,
    operation_id="start_game",
)
async def start_game(
        context: Annotated[Context, Depends(required_access_token_ctx)],
) -> Game:
    return load_game(context.creator, context.auth_account, context.cur)


@router.get(
    path="/balance",
    response_model=int,
    operation_id="game_balance",
)
async def game_balance(
        context: Annotated[Context, Depends(required_access_token_ctx)],
) -> int:
    creator = check_creator(context.creator, context.auth_account)
    points = load_creator_points(creator.creator_id, context.auth_account.userid, context.cur)
    return points.total_points()


@router.get(
    path="/pick-a-hole/{hole_idx}",
    response_model=Game,
    operation_id="pick_a_hole",
)
async def pick_a_hole(
        context: Annotated[Context, Depends(required_access_token_ctx)],
        hole_idx: int,
) -> Game:
    game = load_game(context.creator, context.auth_account, context.cur)
    if game.remaining_games < 1:
        raise APIError(APIError.INTERNAL, "You have not attempts left. Try to back next day")

    game.pick_a_hole(hole_idx)
    GameNotifications.update_season2(
        game.creator_id,
        Season2Result(
            reward=game.game_result.reward
            if game.game_result and game.game_result.reward else 0
        ),
        context.cur,
    )

    return game
