from .common.config import Config
from typing import Generic, TypeVar, Type, Any
from pydantic import BaseModel, Field
import redis
import logging


logger = logging.getLogger(__name__)


class RedisConnection:
    connection: redis.Redis

    @staticmethod
    def init() -> None:
        logger.info(f"Initializing Redis connection...")
        RedisConnection.connection = redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            username=Config.REDIS_USERNAME,
            password=Config.REDIS_PASSWORD,
        )


CachedObjectType = TypeVar("CachedObjectType", bound=BaseModel)


class CachedObject(BaseModel, Generic[CachedObjectType]):
    cache_key: str = Field(exclude=True)
    cls: Type[CachedObjectType] = Field(exclude=True)
    instance: CachedObjectType = Field(exclude=True)

    def model_post_init(self, __context: Any) -> None:
        RedisConnection.connection.set(self.cache_key, self.instance.model_dump_json())

    def __setattr__(self, key: str, value: Any) -> None:
        if key in self.model_fields_set:
            super(BaseModel, self).__setattr__(key, value)
        else:
            self.instance.__setattr__(key, value)
            self.upload()

    def __getattr__(self, key: str) -> Any:
        if key in self.model_fields_set:
            return super(BaseModel, self).__getattr__(key)
        else:
            self.refresh()
            return self.instance.__getattribute__(key)

    def __getitem__(self, item: str) -> Any:
        return self.instance[item]

    def get(self, key: str, default: Any) -> Any:
        self.refresh()
        return self.instance.get(key, default)

    def upload(self) -> None:
        RedisConnection.connection.set(self.cache_key, self.instance.model_dump_json())

    def refresh(self) -> None:
        tmp = RedisConnection.connection.get(self.cache_key)
        if tmp is None:
            return

        instance = self.cls.model_validate_json(tmp)
        super().__setattr__("instance", instance)
