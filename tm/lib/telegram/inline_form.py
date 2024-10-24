from attr import dataclass
from telegram import Message, InputMedia, InlineKeyboardMarkup, MaybeInaccessibleMessage, User
from telegram.constants import ParseMode
from typing import Dict, Optional
import logging

from ..authentication.auth_account import AuthAccount
from ..common.api_error import APIError
from ..creator import Creator


logger = logging.getLogger(__name__)

@dataclass
class BaseFormPage:
    async def picture(self, _user: User, _creator: Creator | None) -> str:
        logger.error("BaseFormPage.picture not implemented")
        raise APIError(APIError.INTERNAL, "Unexpected error. Please, contact customer support for details")

    async def caption(self, _user: User, _creator: Creator | None) -> str | None:
        logger.error("BaseFormPage.caption not implemented")
        raise APIError(APIError.INTERNAL, "Unexpected error. Please, contact customer support for details")

    async def markup(self, _user: User, _creator: Creator | None) -> InlineKeyboardMarkup | None:
        logger.error("BaseFormPage.markup not implemented")
        raise APIError(APIError.INTERNAL, "Unexpected error. Please, contact customer support for details")

    async def build(
            self,
            message: Message,
            user: User,
            update: bool,
            creator: Creator | None,
    ) -> None:
        if update:
            picture = await self.picture(user, creator)
            caption = await self.caption(user, creator)
            markup = await self.markup(user, creator)
            await message.edit_media(media=InputMedia(media_type="photo", media=picture))
            await message.edit_caption(caption, markup, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await message.reply_photo(
                photo=await self.picture(user, creator),
                caption=await self.caption(user, creator),
                parse_mode=ParseMode.MARKDOWN_V2,
                protect_content=True,
                reply_markup=await self.markup(user, creator)
            )

    async def process_callback_query(
            self,
            _query: str,
            _message: Message,
            _user: User,
            _creator: Creator | None,
            _auth_account: AuthAccount,
    ) -> str | None:
        logger.error(f"BaseFormPage.process_callback_query")
        raise APIError(APIError.INTERNAL, "Unexpected error. Please, contact customer support")


@dataclass
class InlineForm:
    pages: Dict[str, BaseFormPage]
    init_page: str

    async def show(self, message: Message, user: User, creator: Creator | None) -> None:
        init_page = self.pages[self.init_page]
        await init_page.build(message, user, False, creator)

    async def process_callback_query(
            self,
            query: str,
            message: Optional[MaybeInaccessibleMessage],
            user: Optional[User],
            creator: Creator | None,
            auth_account: AuthAccount,
    ) -> None:
        if not message or not user:
            return

        [page_name, _] = query.split(".")
        page = self.pages[page_name]
        new_page_name = await page.process_callback_query(query, message, user, creator, auth_account)
        new_page = self.pages[new_page_name] if new_page_name else None
        if new_page:
            await new_page.build(message, user, update=True, creator=creator)
