from fastapi import APIRouter, Depends
from typing import Annotated
import logging
from typing import Dict

from .whack_a_mole_api import check_creator
from ..common.api_error import APIError
from .common import Context, required_access_token_ctx


from ..game_tasks import Task as GameTask, GameTasks, VoteResult, YesNoResult
from ..game_notifications import GameNotifications

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.get(
    path="/",
    response_model=Dict[str, GameTask],
    operation_id="get_tasks"
)
async def get_tasks(
        context: Annotated[Context, Depends(required_access_token_ctx)],
) -> Dict[str, GameTask]:
    creator = check_creator(context.creator, context.auth_account)
    return GameTasks.get_available_tasks(
        creator.creator_id,
        context.auth_account.userid,
        context.cur
    )


@router.post(
    path="/vote/{task_name}",
    operation_id="vote_task"
)
async def vote_task(
        context: Annotated[Context, Depends(required_access_token_ctx)],
        task_name: str,
        task_result: VoteResult,
) -> None:
    creator = check_creator(context.creator, context.auth_account)
    GameNotifications.vote(
        creator.creator_id,
        task_name, task_result,
        context.auth_account.userid,
        context.cur
    )


@router.post(
    path="/yes_no/{task_name}",
    operation_id="vote_yes_no"
)
async def vote_yes_no(
        context: Annotated[Context, Depends(required_access_token_ctx)],
        task_name: str,
        task_result: YesNoResult,
) -> None:
    creator = check_creator(context.creator, context.auth_account)
    GameNotifications.vote_yes_no(
        creator.creator_id,
        task_name, task_result,
        context.auth_account.userid,
        context.cur
    )
