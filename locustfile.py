import string

from locust import HttpUser, task, between, events
from typing import get_args
import random
import time

from tm.lib.common.config import Config
from tm.lib.authentication.access_token import create_access_token
from tm.lib.authentication.auth_account_factory import AuthAccountFactory
from tm.lib.authentication.auth_account import PlatformType
from tm.lib.common.database import Database

Config.init()
Database.init()
PLATFORM_NAMES = [p for p in get_args(PlatformType) if p not in ["admin", "nowhere"]]

def random_platform() -> PlatformType:
    return "tg"


def random_userid(platform: PlatformType):
    result = ''.join([random.choice(string.digits) for _ in range(10)])
    if platform == "wa":
        return "+" + result

    return result


def random_username():
    return "test_" + ''.join([random.choice(string.ascii_letters) for _ in range(10)])


HEX_SYMBOLS = [
    '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'c', 'd', 'e', 'f'
]

def random_eth_address() -> str:
    return "0x" + "".join([random.choice(HEX_SYMBOLS) for _ in range(40)])


class RegisteringUser(HttpUser):
    wait_time = between(5, 10)

    @task
    def register_user(self):
        cur = Database.begin()
        platform = random_platform()
        auth_account = AuthAccountFactory.create_or_update(
            platform, random_userid(platform), random_username(), cur,
        )
        Database.commit()

        self.client.get(
            url="/api/settings/crypto_networks"
        )

        access_token = create_access_token(auth_account)
        self.client.post(
            url=f"/api/creator",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=f"passphrase={Config.CLIENT_PASS_PHRASE}",
        )

        time.sleep(1)
        self.client.get(
            url="/api/creator",
            headers={
                "Authorization": f"Bearer {access_token}",
            },
        )

        self.client.post(
            url="/api/creator/country/?new_country=Antarctica",
            headers={
                "Authorization": f"Bearer {access_token}",
            },
        )

        time.sleep(5)
        self.client.post(
            url=f"/api/creator/payout_channel/crypto",
            headers={
                "Authorization": f"Bearer {access_token}",
            },
            json={
                "network": "Polygon",
                "address": random_eth_address(),
                "currency": "USDC",
            }
        )


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    # Cleaning up test data
    cur = Database.begin()
    cur.execute(
        """
        DELETE FROM public.notification AS n
        USING
            public.auth_account AS aa, 
            public.creator AS c
        WHERE
            aa.username LIKE 'test_%'
            AND aa.creator_id = c.creator_id
            AND c.creator_id = n.creator_id;
        """
    )

    cur.execute(
        """
        DELETE FROM public.provider_account AS pa
        USING 
            public.payout_channel AS pc, 
            public.auth_account AS aa, 
            public.creator AS c
        WHERE
            aa.username LIKE 'test_%'
            AND aa.creator_id = c.creator_id
            AND pc.creator_id = c.creator_id
            AND pa.channel_id = pc.channel_id;
        """
    )

    cur.execute(
        """
        DELETE FROM public.payout_channel AS pc
        USING 
            public.auth_account AS aa, 
            public.creator AS c
        WHERE
            aa.username LIKE 'test_%'
            AND aa.creator_id = c.creator_id
            AND pc.creator_id = c.creator_id;
        """
    )

    cur.execute(
        """
        WITH accounts_to_delete AS (
            DELETE FROM public.auth_account AS aa
            USING public.creator AS c
            WHERE 
                aa.creator_id = c.creator_id 
                AND aa.username LIKE 'test_%' 
                OR aa.creator_id IS NULL
            RETURNING aa.creator_id
        )
        DELETE FROM public.creator AS c
        USING accounts_to_delete AS atd
        WHERE atd.creator_id = c.creator_id;
        """
    )
    Database.commit()