import requests
import requests.adapters
import logging
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from ..common.config import Config
from ..common.api_error import APIError
from .profile_picture_saver import save_profile_picture

logger = logging.getLogger(__name__)

STARTUP_TEMPLATE = {
    "template_type": "generic",
    "elements": [
        {
            "title": "Welcome to TransferMole!",
            "image_url": "https://app.transfermole.com/pictures/transfermole.jpg",
            "subtitle": "The clever way to get paid without sharing transfer details, personal data or crypto addresses.",
            "default_action": {
                "type": "web_url",
                "url": "https://www.transfermole.com",
            },
            "buttons": [
                {
                    "type": "postback",
                    "title": "Register",
                    "payload": "register"
                }, {
                    "type": "postback",
                    "title": "Make Payment",
                    "payload": "transfer"
                }, {
                    "type": "postback",
                    "title": "Support",
                    "payload": "support"
                }
            ]
        }
    ]
}

INVITE_ONLY_FORM = {
    "template_type": "generic",
    "elements": [
        {
            "title": "Access is currently invite only",
            "image_url": "https://app.transfermole.com/pictures/transfermole.jpg",
            "subtitle": "Sign up below to our waitlist and we'll let you know when we onboard next batch",
            "default_action": {
                "type": "web_url",
                "url": "https://www.transfermole.com",
            },
            "buttons": [
                {
                    "type": "postback",
                    "title": "Get on waitlist",
                    "payload": "waitlist"
                }, {
                    "type": "postback",
                    "title": "Support",
                    "payload": "support"
                }
            ]
        }
    ]
}


def create_creator_menu(username: str) -> Dict[str, Any]:
    return {
        "template_type": "generic",
        "elements": [
            {
                "title": f"Hello @{username}",
                "subtitle": "What do you want to do?",
                "buttons": [
                    {
                        "type": "postback",
                        "title": "Open Dashboard",
                        "payload": "dashboard"
                    }, {
                        "type": "postback",
                        "title": "Make Payment",
                        "payload": "transfer"
                    }, {
                        "type": "postback",
                        "title": "Get my payment link",
                        "payload": "payment_link",
                    }
                ]
            }
        ]
    }


def create_registration_template(username: str, link: str, expired_mins: int) -> Dict[str, Any]:
    return {
        "template_type": "generic",
        "elements": [
            {
                "title": f"Registration link for @{username}",
                "subtitle": "Click button below to proceed to registration page. "
                            f"NOTE: This link will be available {expired_mins} minutes",
                "buttons": [
                    {
                        "type": "web_url",
                        "url": f"{link}",
                        "title": "Proceed to registration"
                    }
                ]
            }
        ]
    }


def create_dashboard_template(username: str, link: str, expired_mins: int) -> Dict[str, Any]:
    return {
        "template_type": "generic",
        "elements": [
            {
                "title": f"Dashboard for @{username}",
                "subtitle": "Click button below to proceed to your personal dashboard. "
                            f"NOTE: This link will be available {expired_mins} minutes",
                "buttons": [
                    {
                        "type": "web_url",
                        "url": f"{link}",
                        "title": "Proceed to dashboard"
                    }
                ]
            }
        ]
    }


class IGProfileInfo(BaseModel):
    userid: str
    username: str
    name: Optional[str] = Field(default=None)
    profile_pic: Optional[str] = Field(default=None)
    follower_count: int = Field(default=0)


class InstagramAPI:
    session: requests.Session

    @staticmethod
    def init() -> None:
        logger.info("Initializing InstagramAPI...")
        InstagramAPI.session = requests.Session()
        InstagramAPI.setup_ice_breakers()
        InstagramAPI.setup_persistent_menu()

    @staticmethod
    def cleanup() -> None:
        logger.info("Cleaning instagram menu and icebreakers...")
        InstagramAPI.session = requests.Session()
        InstagramAPI.delete_persistent_menu()
        InstagramAPI.delete_ice_breakers()

    @staticmethod
    def send_simple_message(userid: str, text: str) -> bool:
        try:
            url = f'{Config.FACEBOOK_API}/me/messages?access_token={Config.PAGE_ACCESS_TOKEN}'
            data = 'recipient={"id":"' + userid + '"}&message={"text":"' + text + '"}'
            response = InstagramAPI.session.post(url=url, data=data)
            if response.status_code != 200:
                logger.error(f"Failed to send message ({response.status_code}): {response.text}")
                return False

            return True
        except Exception as e:
            logger.warning(f"Failed to send message: {e}")
            return False

    @staticmethod
    def get_profile_info(userid: str) -> IGProfileInfo:
        response = InstagramAPI.session.get(
            url=f'{Config.FACEBOOK_API}/{userid}?access_token={Config.PAGE_ACCESS_TOKEN}',
        )
        if response.status_code != 200:
            logger.warning(f"Failed to get IG profile info ({response.status_code}). JSON: {response.text}")
            raise APIError(APIError.INSTAGRAM_ERROR, f"IG User {userid} not found")

        ig_profile = response.json()
        userid = ig_profile["id"]
        username = ig_profile["username"].lower()
        name = ig_profile.get("name", None)
        profile_pic_url = save_profile_picture("ig", userid, ig_profile.get("profile_pic", None))
        follower_count = ig_profile.get("follower_count", None)
        # preprocess
        username = username.lower()

        return IGProfileInfo(
            userid=userid, username=username, name=name, profile_pic=profile_pic_url, follower_count=follower_count
        )

    @staticmethod
    def delete_ice_breakers() -> None:
        data = {
            "fields": [
                "ice_breakers",
            ]
        }

        url = (f"{Config.FACEBOOK_API}/me/messenger_profile?"
               f"platform=instagram&access_token={Config.PAGE_ACCESS_TOKEN}")

        try:
            response = InstagramAPI.session.delete(url, json=data)
            if response.status_code != 200:
                logger.error(f"Failed to setup icebreakers ({response.status_code}): {response.text}")
        except Exception as e:
            logger.warning(f"Failed to send ice breakers: {e}")

    @staticmethod
    def setup_ice_breakers() -> None:
        data = {
            "platform": "instagram",
            "ice_breakers": [
                {
                    "call_to_actions": [
                        {
                            "question": "Register",
                            "payload": "register"
                        }, {
                            "question": "Make Payment",
                            "payload": "transfer"
                        }, {
                            "question": "Support",
                            "payload": "support"
                        }
                    ],
                    "locale": "default"
                }
            ]
        }

        url = (f"{Config.FACEBOOK_API}/me/messenger_profile?"
               f"platform=instagram&access_token={Config.PAGE_ACCESS_TOKEN}")

        try:
            response = InstagramAPI.session.post(url, json=data)
            if response.status_code != 200:
                logger.error(f"Failed to setup icebreakers ({response.status_code}): {response.text}")
        except Exception as e:
            logger.warning(f"Failed to send ice breakers: {e}")

    @staticmethod
    def delete_persistent_menu() -> None:
        url = (f'{Config.FACEBOOK_API}/me/messenger_profile?fields=["persistent_menu"]&'
               f'platform=instagram&access_token={Config.PAGE_ACCESS_TOKEN}')
        try:
            response = InstagramAPI.session.delete(url)
            if response.status_code != 200:
                logger.error(f"Failed to setup persistent menu ({response.status_code}): {response.text}")
        except Exception as e:
            logger.warning(f"Failed to send persistent menu: {e}")

    @staticmethod
    def setup_persistent_menu() -> None:
        data = {
            "persistent_menu": [
                {
                    "locale": "default",
                    "call_to_actions": [
                        {
                            "type": "postback",
                            "title": "Register",
                            "payload": "register"
                        }, {
                            "type": "postback",
                            "title": "Make Payment",
                            "payload": "transfer"
                        }, {
                            "type": "postback",
                            "title": "Support",
                            "payload": "support"
                        }
                    ],
                }
            ]
        }

        url = (f"{Config.FACEBOOK_API}/me/messenger_profile?"
               f"platform=instagram&access_token={Config.PAGE_ACCESS_TOKEN}")

        try:
            response = InstagramAPI.session.post(url, json=data)
            if response.status_code != 200:
                logger.error(f"Failed to setup persistent menu ({response.status_code}): {response.text}")
        except Exception as e:
            logger.warning(f"Failed to send persistent menu: {e}")

    @staticmethod
    def send_template(userid: str, template: dict) -> None:
        data = {
            "recipient": {"id": userid},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": template
                }
            }
        }

        url = f"{Config.FACEBOOK_API}/me/messages?access_token={Config.PAGE_ACCESS_TOKEN}"
        try:
            response = InstagramAPI.session.post(url, json=data)
            if response.status_code != 200:
                logger.error(f"Failed to send template ({response.status_code}): {response.text}")
        except Exception as e:
            logger.warning(f"Failed to send template: {e}")
