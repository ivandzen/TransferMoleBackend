import logging

from .config import Config
import psycopg2
import psycopg2.extras
from time import sleep
from typing import Any


logger = logging.getLogger(__name__)


class Database:
    _conn: Any = None

    @staticmethod
    def init() -> None:
        psycopg2.extras.register_uuid()
        Database._reconnect()

    @staticmethod
    def _reconnect() -> None:
        logger.info("Initializing Database connection...")
        # Close old connection
        if Database._conn:
            Database._conn.close()

        # Reconnect
        Database._conn = psycopg2.connect(
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            host=Config.DB_HOST
        )

    @staticmethod
    def begin() -> psycopg2.extensions.cursor:
        try:
            return Database._conn.cursor()
        except psycopg2.InterfaceError as e:
            logger.info(f'{e} - Database connection will be reset')
            sleep(2)
            Database._reconnect()
            return Database._conn.cursor()

    @staticmethod
    def commit() -> None:
        try:
            Database._conn.commit()
        except psycopg2.InterfaceError as e:
            logger.info(f'{e} - Database connection will be reset')
            sleep(2)
            Database._reconnect()

    @staticmethod
    def rollback() -> None:
        try:
            Database._conn.rollback()
        except psycopg2.InterfaceError as e:
            logger.info(f'{e} - Database connection will be reset')
            sleep(2)
            Database._reconnect()
