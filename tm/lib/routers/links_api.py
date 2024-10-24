import uuid
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import RedirectResponse
import logging

from ..authentication.auth_account_factory import AuthAccountFactory
from ..common.database import Database
from ..common.api_error import APIError
from ..creator_loader import CreatorLoader
from ..game_notifications import GameNotifications
from ..links import LinkType

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/links", tags=["links"])


async def user_clicked_link(creator_id: uuid.UUID, link_type: LinkType) -> None:
    try:
        cur = Database.begin()
        creator = CreatorLoader.get_creator_by_id(creator_id, cur)
        if not creator:
            return

        auth_accounts = AuthAccountFactory.load_creator_accounts(creator_id, cur)
        for auth_account in auth_accounts:
            if auth_account.platform == "tg":
                GameNotifications.link_clicked(creator_id, link_type, auth_account.userid, cur)
                break

        Database.commit()
    except Exception as e:
        logger.error(f"Failed to process user clicked event for creator_id={creator_id} link_type={link_type}: {e}")
        Database.rollback()


@router.get(
    path="/go",
    operation_id='go_link',
)
async def go_link(
        link_type: LinkType,
        creator_id: uuid.UUID,
        background_tasks: BackgroundTasks,
) -> RedirectResponse:
    match link_type:
        case "wp_prod_acc":
            redirect_url = "https://warpcast.com/transfermole"
        case "tg_prod_chat":
            redirect_url = "https://t.me/transfermole"
        case "ig_prod_acc":
            redirect_url = "https://www.instagram.com/gotransfermole/"
        case "x_prod_acc":
            redirect_url = "https://x.com/gotransfermole"
        case "x_ceo_acc":
            redirect_url = "https://x.com/rogerg8001"
        case "x_cto_acc":
            redirect_url = "https://x.com/theivanloboda"
        case "x_cmo_acc":
            redirect_url = "https://x.com/cryptohontas"
        case unknown:
            raise APIError(APIError.INTERNAL, f"Unknown link type {unknown}")

    background_tasks.add_task(user_clicked_link, creator_id, link_type)
    return RedirectResponse(redirect_url)
