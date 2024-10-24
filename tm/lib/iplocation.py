import requests
import logging

from .common.config import Config
from .country import Country
from .country_cache import CountryCache


logger = logging.getLogger(__name__)
http_session = requests.session()

def iplocation(ip_str: str) -> Country | None:
    logger.info("Requesting user location over iplocation.net")
    response = http_session.get(f"https://api.iplocation.net/?ip={ip_str}")
    if response.status_code != 200 or not response.json():
        return None

    return CountryCache.get_country_by_code(response.json()["country_code2"])


def findip(ip_str: str) -> Country | None:
    logger.info("Requesting user location over findip.net")
    response = http_session.get(f"https://api.findip.net/{ip_str}/?token={Config.FINDIP_TOKEN}")
    if response.status_code != 200 or not response.json():
        return None

    return CountryCache.get_country_by_code(response.json()["country"]["iso_code"])


def get_ip_location(ip_str: str) -> Country | None:
    return findip(ip_str)
