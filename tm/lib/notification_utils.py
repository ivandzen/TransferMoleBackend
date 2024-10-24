import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Optional, Callable, List, Awaitable, Tuple, Any
from psycopg2.extensions import cursor

from .common.database import Database
from .authentication.auth_account import AuthAccount
from .authentication.auth_account_factory import AuthAccountFactory
from .notification import BaseNotification, logger, EventCategory, Notification, NotificationData


async def notification_task(
        creator_id: uuid.UUID,
        notification: BaseNotification,
        after_completion: Optional[Callable[[List[AuthAccount], cursor], Awaitable[None]]],
) -> None:
    try:
        cur = Database.begin()
        cur.execute(
            'INSERT INTO public.notification (creator_id, category, subcategory, data_jsonb) '
            'VALUES(%s, %s, %s, %s) '
            'RETURNING notification_id, created_at;',
            (creator_id, notification.category, notification.subcategory, notification.model_dump_json(),)
        )

        entry = cur.fetchone()
        if not entry:
            Database.rollback()
            logger.error(f"Failed to register notification: creator_id = {creator_id}, notification = {notification}")
            return

        Database.commit()
        auth_accounts = AuthAccountFactory.load_creator_accounts(creator_id, cur)
        await notification.send(auth_accounts)

        if after_completion:
            await after_completion(auth_accounts, cur)

        Database.commit()
    except Exception as e:
        logger.error(f"Failed to register event: creator_id = {creator_id}, notification = {notification}: {e}")
        Database.rollback()


def send_notification(
        creator_id: uuid.UUID,
        notification: BaseNotification,
        after_completion: Optional[Callable[[List[AuthAccount], cursor], Awaitable[None]]],
) -> None:
    asyncio.create_task(notification_task(creator_id, notification, after_completion))


def get_notifications(
        category: EventCategory | None,
        creator_id: uuid.UUID | None,
        from_time: datetime | None,
        duration: timedelta | None,
        cur: cursor
) -> List[Notification]:
    query = (
        'SELECT notification_id, created_at, creator_id, category, data_jsonb '
        'FROM public.notification'
    )
    params: Tuple[Any, ...] = ()

    if category:
        query += " WHERE category = %s"
        params += (category,)

    where_or_and = lambda : " AND" if len(params) else " WHERE"

    if creator_id:
        query += f" {where_or_and()} creator_id = %s"
        params += (creator_id,)

    if from_time:
        query += f" {where_or_and()} created_at >= %s "
        params += (from_time,)
        if duration:
            query += f" {where_or_and()} created_at <= %s "
            params += (from_time + duration,)

    query += " ORDER BY created_at DESC;"

    cur.execute(query, params)
    result: List[Notification] = []
    for entry in cur:
        result.append(
            Notification(
                notification_id=entry[0],
                created_at=entry[1],
                creator_id=entry[2],
                data=NotificationData.model_validate(entry[4]),
            )
        )

    return result
