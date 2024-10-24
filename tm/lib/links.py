import uuid
from typing import Literal

from .common.config import Config

LinkType = Literal[
    "wp_prod_acc",
    "tg_prod_chat",
    "ig_prod_acc",
    "x_prod_acc",
    "x_ceo_acc",
    "x_cto_acc",
    "x_cmo_acc"
]


def get_link(creator_id: uuid.UUID, link_type: LinkType) -> str:
    return f"{Config.USER_UI_BASE}/api/links/go?creator_id={creator_id}&link_type={link_type}"
