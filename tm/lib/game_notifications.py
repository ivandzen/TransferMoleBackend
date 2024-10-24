import uuid
from typing import Any
from psycopg2.extensions import cursor

from .common.api_error import APIError
from .creator_points import add_creator_points
from .game_tasks import GameTasks, YesNoResult, VoteResult, Season2Result
from .notification import TaskCompleted
from .notification_utils import send_notification

REFERRAL_POINTS = 300
REFERREE_POINTS = 2500

class GameNotifications:
    @staticmethod
    def _complete_task(creator_id: uuid.UUID, task_name: str, task_result: Any) -> None:
        send_notification(
            creator_id,
            TaskCompleted(
                subcategory=task_name,
                task_result=task_result,
            ),
            None
        )

    @staticmethod
    def link_clicked(creator_id: uuid.UUID, task_name: str, tg_userid: str, cur: cursor) -> None:
        task = GameTasks.get_task(creator_id, task_name, "link", tg_userid, cur)
        if task is None:
            return

        task.root.complete(creator_id, cur)
        GameNotifications._complete_task(creator_id, task.root.task_name, None)

    @staticmethod
    def vote_yes_no(creator_id: uuid.UUID, task_name: str, task_result: YesNoResult, tg_userid: str, cur: cursor) -> None:
        task = GameTasks.get_task(creator_id, task_name, "yes-no-question", tg_userid, cur)
        if task is None:
            raise APIError(APIError.INTERNAL, f"Vote task {task_name} not found")

        task.root.complete(creator_id, cur)
        GameNotifications._complete_task(creator_id, task.root.task_name, task_result)

    @staticmethod
    def vote(creator_id: uuid.UUID, task_name: str, task_result: VoteResult, tg_userid: str, cur: cursor) -> None:
        task = GameTasks.get_task(creator_id, task_name, "vote-question", tg_userid, cur)
        if task is None:
            raise APIError(APIError.INTERNAL, f"Vote task {task_name} not found")

        task.root.complete(creator_id, cur)
        GameNotifications._complete_task(creator_id, task.root.task_name, task_result)

    @staticmethod
    def update_season2(creator_id: uuid.UUID, task_result: Season2Result, cur: cursor) -> None:
        add_creator_points(creator_id, "season2", task_result.reward, cur)
        GameNotifications._complete_task(creator_id, "season2", task_result)

    @staticmethod
    def new_referree(referral: uuid.UUID | None, referree: uuid.UUID, cur: cursor) -> None:
        add_creator_points(referree, 'referral_program', REFERREE_POINTS, cur)
        if referral:
            # referral may be deleted and unable to receive points. But referree will still receive
            add_creator_points(referral, 'referral_program', REFERRAL_POINTS, cur)
