import datetime
import os
import logging
import decimal


logger = logging.getLogger(__name__)


def parse_bool(s: str) -> bool:
    sl = s.lower()
    if sl in ['true', 'yes', 'y', '1']:
        return True
    if sl in ['false', 'no', 'n', '0']:
        return False
    raise Exception(f"Unexpected boolean value: {s}")


class Config:
    FACEBOOK_API: str | None
    USER_UI_BASE: str | None
    WEBHOOK_TOKEN: str | None
    PAGE_ACCESS_TOKEN: str | None
    DB_NAME: str | None
    DB_USER: str | None
    DB_PASSWORD: str | None
    DB_HOST: str | None
    IGNORE_CHECK_FB_WEBHOOK_SIGNATURE: str | None
    APP_SECRET: str | bytes | None
    PRODUCTION: bool | None
    ACCESS_TOKEN_LIFETIME: datetime.timedelta
    STRIPE_USER: str | None
    STRIPE_PASS: str | None
    STRIPE_CONNECT_WEBHOOK_SECRET: str
    STRIPE_ACCOUNT_WEBHOOK_SECRET: str
    PROFILE_PIC_DIR: str | None
    CLIENT_PASS_PHRASE: str | None
    ETHEREUM_RPC: str
    POLYGON_RPC: str
    AVALANCHE_CCHAIN_RPC: str
    BASE_BLOCKCHAIN_RPC: str
    BSC_BLOCKCHAIN_RPC: str
    MANYCHAT_TOKEN: str | None
    LIVE_STRIPE_KEY: str | None
    AUTH0_DOMAIN: str
    AUTH0_CLIENT_ID: str
    AUTH0_CLIENT_SECRET: str
    SERVER_PRIVATE_KEY: bytes
    SERVER_PUBLIC_KEY: bytes
    ENABLED_APIS: list[str]
    REDIS_HOST: str
    REDIS_PORT: str
    REDIS_USERNAME: str
    REDIS_PASSWORD: str
    FINDIP_TOKEN: str
    TRANSFERMOLE_FEE_USD: int
    MAKE_HOOK: str
    TRANSFER_MINIMUM_USD: decimal.Decimal
    TRANSFER_MAXIMUM_USD: decimal.Decimal
    CIRCLE_API_KEY: str
    MERCURYO_MODE: str
    MERCURYO_WIDGET_ID: str
    MERCURYO_SECRET: str
    MERCURYO_SDK_PARTNER_TOKEN: str
    MERCURYO_SIGN_KEY: str
    SUMSUB_WEBSDK_SECRET_KEY: str
    SUMSUB_APP_TOKEN: str
    SUMSUB_APP_SECRET_KEY: str
    SUMSUB_KYC_LEVEL: str
    SUMSUB_WEBHOOK_SECRET_KEY: str
    TELEGRAM_BOT_TOKEN: str
    MAKE_USER_GAME_STATUS: str
    DISABLE_NOTIFICATIONS: bool
    TELEGRAM_REPORTER_BOT_TOKEN: str
    TELEGRAM_BOT_WHOOK_SECRET_TOKEN: str

    @staticmethod
    def init() -> None:
        logger.info("Initializing Config module...")
        Config.FACEBOOK_API = os.environ.get("FACEBOOK_API", "https://graph.facebook.com/v17.0")
        Config.USER_UI_BASE = os.environ.get("USER_UI_BASE", None)
        Config.WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN", None)
        Config.PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", None)
        Config.DB_NAME = os.environ.get("DB_NAME", None)
        Config.DB_USER = os.environ.get("DB_USER", None)
        Config.DB_PASSWORD = os.environ.get("DB_PASSWORD", None)
        Config.DB_HOST = os.environ.get("DB_HOST", None)
        Config.IGNORE_CHECK_FB_WEBHOOK_SIGNATURE = os.environ.get("IGNORE_CHECK_FB_WEBHOOK_SIGNATURE", False)
        Config.APP_SECRET = os.environ.get("APP_SECRET", None)
        Config.PRODUCTION = parse_bool(os.environ.get("PRODUCTION", "True"))
        Config.ACCESS_TOKEN_LIFETIME = datetime.timedelta(
            minutes=int(os.environ.get("ACCESS_TOKEN_LIFETIME_MINUTES", "60"))
        )
        Config.STRIPE_USER = os.environ.get("STRIPE_USER", None)
        Config.STRIPE_PASS = os.environ.get("STRIPE_PASS", "")
        Config.STRIPE_CONNECT_WEBHOOK_SECRET = os.environ.get("STRIPE_CONNECT_WEBHOOK_SECRET", None)
        Config.STRIPE_ACCOUNT_WEBHOOK_SECRET = os.environ.get("STRIPE_ACCOUNT_WEBHOOK_SECRET", None)
        Config.PROFILE_PIC_DIR = os.environ.get("PROFILE_PIC_DIR", None)
        Config.CLIENT_PASS_PHRASE = os.environ.get("CLIENT_PASS_PHRASE", None)
        Config.ETHEREUM_RPC = os.environ.get("ETHEREUM_RPC", None)
        Config.POLYGON_RPC = os.environ.get("POLYGON_RPC", None)
        Config.AVALANCHE_CCHAIN_RPC = os.environ.get("AVALANCHE_CCHAIN_RPC", None)
        Config.BASE_BLOCKCHAIN_RPC = os.environ.get("BASE_BLOCKCHAIN_RPC", None)
        Config.BSC_BLOCKCHAIN_RPC = os.environ.get("BSC_BLOCKCHAIN_RPC", None)
        Config.MANYCHAT_TOKEN = os.environ.get("MANYCHAT_TOKEN", None)
        Config.LIVE_STRIPE_KEY = os.environ.get("LIVE_STRIPE_KEY", None)
        Config.AUTH0_DOMAIN = os.environ.get("AUTH0_DOMAIN", None)
        Config.AUTH0_CLIENT_ID = os.environ.get("AUTH0_CLIENT_ID", None)
        Config.AUTH0_CLIENT_SECRET = os.environ.get("AUTH0_CLIENT_SECRET", None)
        Config.REDIS_HOST = os.environ.get('REDIS_HOST', None)
        Config.REDIS_PORT = os.environ.get('REDIS_PORT', None)
        Config.REDIS_USERNAME = os.environ.get('REDIS_USERNAME', None)
        Config.REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', None)
        Config.FINDIP_TOKEN = os.environ.get('FINDIP_TOKEN', None)
        Config.MAKE_HOOK = os.environ.get('MAKE_HOOK', None)
        Config.TRANSFER_MINIMUM_USD = decimal.Decimal(os.environ.get('TRANSFER_MINIMUM_USD', None))
        Config.TRANSFER_MAXIMUM_USD = decimal.Decimal(os.environ.get('TRANSFER_MAXIMUM_USD', None))
        Config.CIRCLE_API_KEY = os.environ.get('CIRCLE_API_KEY', None)
        Config.MERCURYO_MODE = os.environ.get('MERCURYO_MODE', 'Sandbox')
        Config.MERCURYO_WIDGET_ID = os.environ.get('MERCURYO_WIDGET_ID', None)
        Config.MERCURYO_SECRET = os.environ.get('MERCURYO_SECRET', None)
        Config.MERCURYO_SDK_PARTNER_TOKEN = os.environ.get('MERCURYO_SDK_PARTNER_TOKEN', None)
        Config.MERCURYO_SIGN_KEY = os.environ.get('MERCURYO_SIGN_KEY', None)
        Config.SUMSUB_WEBSDK_SECRET_KEY = os.environ.get('SUMSUB_WEBSDK_SECRET_KEY', None)
        Config.SUMSUB_APP_TOKEN = os.environ.get('SUMSUB_APP_TOKEN', None)
        Config.SUMSUB_APP_SECRET_KEY = os.environ.get('SUMSUB_APP_SECRET_KEY', None)
        Config.SUMSUB_KYC_LEVEL = os.environ.get('SUMSUB_KYC_LEVEL', None)
        Config.SUMSUB_WEBHOOK_SECRET_KEY = os.environ.get('SUMSUB_WEBHOOK_SECRET_KEY', None)
        Config.TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', None)
        Config.MAKE_USER_GAME_STATUS = os.environ.get('MAKE_USER_GAME_STATUS', None)
        Config.DISABLE_NOTIFICATIONS = parse_bool(os.environ.get('DISABLE_NOTIFICATIONS', 'No'))
        Config.TELEGRAM_REPORTER_BOT_TOKEN = os.environ.get('TELEGRAM_REPORTER_BOT_TOKEN', None)
        Config.TELEGRAM_BOT_WHOOK_SECRET_TOKEN = os.environ.get('TELEGRAM_BOT_WHOOK_SECRET_TOKEN', None)

        TRANSFERMOLE_FEE_USD = os.environ.get('TRANSFERMOLE_FEE_USD', None)
        assert (TRANSFERMOLE_FEE_USD is not None)
        Config.TRANSFERMOLE_FEE_USD = int(TRANSFERMOLE_FEE_USD)

        Config.ENABLED_APIS = [
            entry.strip() for entry in os.environ.get("ENABLED_APIS", '').split(',') if len(entry.strip()) > 0
        ]

        assert (Config.USER_UI_BASE is not None)
        assert (Config.WEBHOOK_TOKEN is not None)
        assert (Config.PAGE_ACCESS_TOKEN is not None)
        assert (Config.DB_NAME is not None)
        assert (Config.DB_USER is not None)
        assert (Config.DB_PASSWORD is not None)
        assert (Config.DB_HOST is not None)
        assert (Config.STRIPE_USER is not None)
        assert (Config.STRIPE_CONNECT_WEBHOOK_SECRET is not None)
        assert (Config.STRIPE_ACCOUNT_WEBHOOK_SECRET is not None)
        assert (Config.PROFILE_PIC_DIR is not None)
        assert (Config.ETHEREUM_RPC is not None)
        assert (Config.POLYGON_RPC is not None)
        assert (Config.AVALANCHE_CCHAIN_RPC is not None)
        assert (Config.BASE_BLOCKCHAIN_RPC is not None)
        assert (Config.BSC_BLOCKCHAIN_RPC is not None)
        assert (Config.MANYCHAT_TOKEN is not None)
        assert (Config.AUTH0_DOMAIN is not None)
        assert (Config.AUTH0_CLIENT_ID is not None)
        assert (Config.AUTH0_CLIENT_SECRET is not None)
        assert (Config.REDIS_HOST is not None)
        assert (Config.REDIS_PORT is not None)
        assert (Config.REDIS_USERNAME is not None)
        assert (Config.REDIS_PASSWORD is not None)
        assert (Config.FINDIP_TOKEN is not None)
        assert (Config.MAKE_HOOK is not None)
        assert (Config.CIRCLE_API_KEY is not None)
        assert (Config.MERCURYO_WIDGET_ID is not None)
        assert (Config.MERCURYO_SECRET is not None)
        assert (Config.MERCURYO_SDK_PARTNER_TOKEN is not None)
        assert (Config.MERCURYO_SIGN_KEY is not None)
        assert (Config.SUMSUB_WEBSDK_SECRET_KEY is not None)
        assert (Config.SUMSUB_APP_TOKEN is not None)
        assert (Config.SUMSUB_APP_SECRET_KEY is not None)
        assert (Config.SUMSUB_KYC_LEVEL is not None)
        assert (Config.SUMSUB_WEBHOOK_SECRET_KEY is not None)
        assert (Config.TELEGRAM_BOT_TOKEN is not None)
        assert (Config.MAKE_USER_GAME_STATUS is not None)
        assert (Config.TELEGRAM_BOT_WHOOK_SECRET_TOKEN is not None)

        if not Config.IGNORE_CHECK_FB_WEBHOOK_SIGNATURE and (Config.APP_SECRET is None):
            raise Exception("APP_SECRET not specified")

        Config.APP_SECRET = Config.APP_SECRET.encode()

        # Check and create profile pic directory
        if not os.path.exists(Config.PROFILE_PIC_DIR):
            os.makedirs(Config.PROFILE_PIC_DIR)

        server_private_key_file = os.environ.get("SERVER_PRIVATE_KEY_FILE", None)
        server_public_key_file = os.environ.get("SERVER_PUBLIC_KEY_FILE", None)

        assert (server_private_key_file is not None)
        assert (server_public_key_file is not None)

        with open(server_private_key_file, "rb") as file:
            Config.SERVER_PRIVATE_KEY = file.read()

        with open(server_public_key_file, "rb") as file:
            Config.SERVER_PUBLIC_KEY = file.read()
