import uuid
from pydantic import BaseModel, Field, RootModel
from typing import TypeVar, Generic, Literal, List, Union, Dict, Optional
from psycopg2.extensions import cursor
from telegram import InlineKeyboardButton
from typing_extensions import ClassVar
import logging

from .common.config import Config
from .creator_points import load_creator_points, task_completed
from .referrals import Referrals

logger = logging.getLogger(__name__)

class BaseTaskData(BaseModel):
    description: str


TaskType = Literal['season1', 'season2', 'referral_program', 'link', 'yes-no-question', 'vote-question']
TaskDataType = TypeVar("TaskDataType", bound=BaseTaskData)


class BaseTask(BaseModel, Generic[TaskDataType]):
    task_name: str
    task_type: TaskType
    task_data: TaskDataType

    def points(self) -> int:
        return 0

    def is_active(self, creator_id: uuid.UUID, cur: cursor) -> bool:
        """
        Checks whether this task is available to a given user
        :param creator_id: UUID of a user
        :param cur: DB cursor
        :return:
        """
        return True

    def complete(self, creator_id: uuid.UUID, cur: cursor) -> None:
        task_completed(creator_id, self.task_name, self.points(), cur)

########################################################################################################################

class Season1Task(BaseTask[BaseTaskData]):
    task_type: Literal['season1'] = Field('season1')

########################################################################################################################

class Season2Result(BaseModel):
    reward: int


class Season2Task(BaseTask[BaseTaskData]):
    task_type: Literal['season2'] = Field('season2')

########################################################################################################################

class ReferralTaskData(BaseTaskData):
    referral_points: int
    referree_points: int

class ReferralTaskResult(BaseModel):
    referree: uuid.UUID

class ReferralTask(BaseTask[ReferralTaskData]):
    task_type: Literal['referral_program'] = Field('referral_program')

    def points(self) -> int:
        return self.task_data.referral_points

########################################################################################################################

class LinkTaskData(BaseTaskData):
    points: int
    url: Optional[str] = None


class LinkTask(BaseTask[LinkTaskData]):
    task_type: Literal['link'] = Field('link')

    def points(self) -> int:
        return self.task_data.points

########################################################################################################################

class YesNoTaskData(BaseTaskData):
    points: int
    question: str


class YesNoResult(BaseModel):
    yes: bool


class YesNoTask(BaseTask[YesNoTaskData]):
    task_type: Literal['yes-no-question'] = Field('yes-no-question')

    def points(self) -> int:
        return self.task_data.points

########################################################################################################################

class VoteTaskData(BaseTaskData):
    points: int
    question: str
    options: List[str]


class VoteResult(BaseModel):
    option: int


class VoteTask(BaseTask[VoteTaskData]):
    task_type: Literal['vote-question'] = Field('vote-question')

    def points(self) -> int:
        return self.task_data.points

########################################################################################################################

class Task(RootModel[Union[
    Season1Task,
    Season2Task,
    ReferralTask,
    LinkTask,
    YesNoTask,
    VoteTask,
]]):
    pass

########################################################################################################################

VISIBLE_TASK_TYPES: List[TaskType] = ['referral_program', 'link', 'yes-no-question', 'vote-question']

class GameTasks:
    TASKS: ClassVar[Dict[str, Task]] = {}

    @staticmethod
    def update(cur: cursor) -> None:
        logger.info("Updating GameTasks...")
        cur.execute("SELECT task_name, task_type, task_data FROM public.game_tasks;")
        for entry in cur:
            GameTasks.TASKS[entry[0]] = Task.model_validate({
                "task_name": entry[0],
                "task_type": entry[1],
                "task_data": entry[2],
            })

        task_names = [f"{task_name} [{task.root.task_type}]" for task_name, task in GameTasks.TASKS.items()]
        logger.info(f"Tasks loaded: {task_names}")

    @staticmethod
    def get_all_tasks(creator_id: uuid.UUID, cur: cursor) -> Dict[str, Task]:
        return {
            task_name: task
            for task_name, task in GameTasks.TASKS.items()
            if task.root.is_active(creator_id, cur)
        }

    @staticmethod
    def get_available_tasks(creator_id: uuid.UUID, tg_userid: str, cur: cursor) -> Dict[str, Task]:
        active_tasks = GameTasks.get_all_tasks(creator_id, cur)
        points = load_creator_points(creator_id, tg_userid, cur)
        return {
            task_name: active_tasks[task_name]
            for task_name in active_tasks
            if active_tasks[task_name].root.task_type == "referral_program" or task_name not in points.points
        }

    @staticmethod
    def get_task(creator_id: uuid.UUID, task_name: str, task_type: TaskType, tg_userid: str, cur: cursor) -> Task | None:
        available_tasks = GameTasks.get_available_tasks(creator_id, tg_userid, cur)
        task = available_tasks.get(task_name, None)
        if not task or task.root.task_type != task_type:
            return None

        return task
