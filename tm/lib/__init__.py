import logging
import os

from .common.config import Config
from .common.database import Database
from .crypto_network import CryptoNetworks
from .country_cache import CountryCache
from .currency import Currency
from .redis_cache import RedisConnection
from .game_tasks import GameTasks


def init_transfer_mole() -> None:
    log_levels = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG
    }

    log_level = log_levels.get(os.environ.get("LOG_LEVEL", "INFO"), logging.WARNING)
    logging.basicConfig(level=log_level)

    logging.info("Initializing TransferMole library...")

    Config.init()
    RedisConnection.init()
    Database.init()
    CryptoNetworks.init()

    cur = Database.begin()
    CountryCache.update_cache(cur)
    Currency.update_cache(cur)

    from .payout.providers.payout_provider_cache import PayoutProviders
    PayoutProviders.update_cache(cur)
    GameTasks.update(cur)

    Database.commit()
