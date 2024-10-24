import logging
import uuid
import datetime
import json
from psycopg2.extensions import cursor
from pydantic import BaseModel, RootModel
from typing import Optional, Dict

from .common.config import Config
from .country import Country
from .country_cache import CountryCache


logger = logging.getLogger(__name__)
CREATOR_EXPIRATION_SECONDS = 300


class VerificationState(BaseModel):
    name: str
    description: Optional[str] = None


class VerificationStates(RootModel):
    root: Dict[str, VerificationState]

    def check_requirement(self, kyc_provider_name: str | None) -> bool:
        if not kyc_provider_name:
            return True

        state = self.root.get(kyc_provider_name, None)
        if not state:
            return False

        return state.name == "verified"


class VerificationIntent(BaseModel):
    redirect_url: Optional[str] = None
    sumsub_token: Optional[str] = None


class Creator(BaseModel):
    creator_id: uuid.UUID
    reg_datetime: datetime.datetime
    country: Optional[Country]
    personal_info: Optional[dict]
    removed: bool

    def set_country(self, country_name: str, cur: cursor) -> None:
        self.country = CountryCache.get_country(country_name)
        cur.execute(
            "UPDATE public.creator "
            f"SET country='{country_name}' "
            f"WHERE creator_id=%s AND removed=False;",
            (self.creator_id,)
        )

    def update_personal_info(self, personal_info: dict, cur: cursor) -> None:
        self.personal_info = personal_info
        cur.execute(
            f"UPDATE public.creator "
            f"SET personal_info='{json.dumps(personal_info)}' "
            f"WHERE creator_id = %s;",
            (self.creator_id,)
        )

    def remove(self, cur: cursor) -> None:
        cur.execute(
            f"UPDATE public.creator "
            f"SET removed = True "
            f"WHERE creator_id = %s AND removed = False;",
            (self.creator_id,)
        )

    def get_payment_link(self) -> str:
        return f"{Config.USER_UI_BASE}/pay/{str(self.creator_id)}"
