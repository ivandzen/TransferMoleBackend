import requests
import os
import logging
from telegram import Bot

from ..common.config import Config
from ..common.api_error import APIError
from ..authentication.auth_account import PlatformType


logger = logging.getLogger(__name__)
session = requests.Session()


def get_profile_picture_path(platform: PlatformType, userid: str) -> str:
    directory = f"{Config.PROFILE_PIC_DIR}/{platform}"
    if not os.path.exists(directory):
        os.makedirs(directory)

    return f"{directory}/{userid}.jpg"


def get_profile_picture_url(platform: PlatformType, userid: str) -> str:
    return f"{Config.USER_UI_BASE}/pictures/{platform}/{userid}.jpg"


def save_profile_picture(platform: PlatformType, userid: str, picture_url: str | None) -> str | None:
    if not picture_url:
        return None

    match platform:
        case "ig" | "wa" | "tg":
            picture_url = picture_url.replace('\/', '/')

        case "go" | "tw":
            pass

        case unknown:
            logger.error(f"Unknown platform: {unknown}")
            raise APIError(APIError.INTERNAL)

    try:
        picture_path = get_profile_picture_path(platform, userid)
        logger.debug(f"Saving profile picture from {picture_url} to {picture_path} ...")
        response = session.get(picture_url)
        if response.status_code == 200:

            if os.path.exists(picture_path):
                os.remove(picture_path)

            f = open(picture_path, "wb")
            f.write(response.content)
            f.close()
            logger.info("Profile picture saved")
        else:
            raise APIError(APIError.INTERNAL, "Unable to read profile picture")

    except Exception as e:
        logger.warning(f"Failed to save profile picture: {e}")

    return get_profile_picture_url(platform, userid)


async def save_telegram_profile_picture(userid: str, bot: Bot, file_id: str) -> str:
    file = await bot.get_file(file_id)
    picture_path = get_profile_picture_path("tg", userid)
    logger.info(f"Saving telegram profile picture to {picture_path}")
    await file.download_to_drive(picture_path)
    return get_profile_picture_url("tg", userid)

