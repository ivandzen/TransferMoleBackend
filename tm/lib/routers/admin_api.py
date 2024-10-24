import uuid
import logging
from datetime import datetime
from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, field_validator
from typing import Annotated, Dict, List, Optional, Set
from psycopg2.extensions import cursor
from decimal import Decimal
import stripe
import re

from .common import Context, required_access_token_ctx, database_cursor, Duration
from ..common.api_error import APIError
from ..payout.proxy_account import ProxyAccount
from ..payout.account_factory import AccountFactory
from ..country_cache import CountryCache
from ..verification.stripe_account import StripeAccount
from ..common.config import Config
from ..authentication.access_token import create_access_token
from ..authentication.auth_account_factory import AuthAccountFactory
from ..currency import Currency, ExchangeRates
from ..payout.providers.payout_provider import ProviderParameters
from ..payout.providers.payout_provider_cache import PayoutProviders
from ..verification.internal_kyc_provider import INTERNAL_KYC_PROVIDER, InternalKYCHistory, InternalKYCStep
from ..payout.bank_account import BankAccountData
from ..crypto_network import CRYPTO_PAYMENT_TYPES
from ..notification import EventCategory, Notification
from ..notification_utils import get_notifications

logger = logging.getLogger(__name__)
admin_router = APIRouter(prefix="/admin", tags=["admin"])
URL_REGEXP = re.compile('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\), ]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')


def check_url(string: str) -> None:
    if not URL_REGEXP.match(string):
        raise APIError(
            APIError.WRONG_PARAMETERS,
            f"correct URL expected"
        )


def check_api_str(string: str) -> None:
    if string is None:
        return

    if isinstance(string, str):
        if len(string) > 50 or '\'' in string or '\"' in string:
            raise APIError(APIError.MESSAGE, f"Message must be shorter than 50 symbols and must not contain quotes")
        return

    raise APIError(APIError.MESSAGE, "Message must be string or empty")


class LoginResponse(BaseModel):
    access_token: str
    token_type: str


@admin_router.post(
    path="/login",
    operation_id="login",
    response_model=LoginResponse
)
async def authenticate(
        form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
        cur: Annotated[cursor, Depends(database_cursor)],
) -> LoginResponse:
    auth_account = AuthAccountFactory.get_by_username("admin", form_data.username, cur)
    if not auth_account:
        raise APIError(
            APIError.ACCESS_ERROR,
            f"User not found"
        )

    auth_account.check_password(form_data.password)
    token = create_access_token(auth_account)
    return LoginResponse(
        access_token=token,
        token_type="bearer",
    )


class SetPasswordParams(BaseModel):
    old_password: str
    new_password: str


@admin_router.post(path="/set_password", operation_id="set_password")
async def set_password(
        params: SetPasswordParams,
        context: Annotated[Context, Depends(required_access_token_ctx)],
) -> None:
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    auth_account = AuthAccountFactory.get_by_userid("admin", context.auth_account.userid, context.cur)
    if not auth_account:
        raise APIError(
            APIError.LOGIN_ERROR,
            "Login or password incorrect"
        )

    auth_account.update_password(params.old_password, params.new_password, context.cur)


@admin_router.get("/proxy_rule/list", operation_id="get_proxy_rules")
async def admin_get_proxy_rules(
        context: Annotated[Context, Depends(required_access_token_ctx)]
) -> Dict[str, Dict[str, Set[uuid.UUID]]]:
    """

    :param context:
    :return: mapping country_name => payment_type => set_of_account_ids
    """
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    result: Dict[str, Dict[str, Set[uuid.UUID]]] = {}
    proxy_accounts = ProxyAccount.get_creator_proxy_rules(context.creator.creator_id, context.cur)
    creator_accounts = AccountFactory.get_creator_owned_accounts(context.creator, context.cur)
    for country, country_proxy_accounts in proxy_accounts.items():
        for proxy_account in country_proxy_accounts:
            term_acc = creator_accounts.get(proxy_account, None)
            if not term_acc:
                logger.warning(f"Account {proxy_account} maybe removed")
                continue

            for provider_account in term_acc.provider_accounts:
                for payment_type in provider_account.supported_payment_types:
                    payment_type = 'crypto' if payment_type in CRYPTO_PAYMENT_TYPES else payment_type
                    (
                        result
                        .setdefault(country, {})
                        .setdefault(payment_type, set())
                        .add(term_acc.payout_channel.channel_id)
                    )

    return result


class ProxyRule(BaseModel):
    country: str
    channel_id: uuid.UUID

    @field_validator("country", mode="before")
    @classmethod
    def validate_country(cls, value: str) -> str:
        CountryCache.get_country(value)
        return value


@admin_router.post("/proxy_rule", operation_id="add_proxy_rule")
async def admin_add_proxy_rule(
        new_rule: ProxyRule, context: Annotated[Context, Depends(required_access_token_ctx)]
) -> None:
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    account_info = AccountFactory.get_account(new_rule.channel_id, context.cur)
    if account_info.payout_channel.creator_id != context.creator.creator_id:
        raise APIError(APIError.ACCESS_ERROR, f"You are not owner of account")

    ProxyAccount.add_proxy_rule(new_rule.country, account_info.payout_channel, context.cur)


@admin_router.delete("/proxy_rule", operation_id="remove_proxy_rule")
async def admin_remove_proxy_rule(
        rule: ProxyRule, context: Annotated[Context, Depends(required_access_token_ctx)]
) -> None:
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    account_info = AccountFactory.get_account(rule.channel_id, context.cur)
    if account_info.payout_channel.creator_id != context.creator.creator_id:
        raise APIError(APIError.ACCESS_ERROR, f"You are not owner of account")

    ProxyAccount.remove_proxy_rule(rule.country, account_info.payout_channel, context.cur)


@admin_router.get(
    path="/stripe_bank_accounts",
    operation_id="get_stripe_bank_accounts",
    response_model=Dict[str, BankAccountData]
)
async def admin_get_stripe_bank_accounts(
        context: Annotated[Context, Depends(required_access_token_ctx)]
) -> Dict[str, BankAccountData]:
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    if context.creator is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, "User not found")

    stripe_account = StripeAccount.get_account_by_creator_id(context.creator.creator_id, context.cur)
    if stripe_account is None:
        raise APIError(APIError.OBJECT_NOT_FOUND, f"Stripe account not found")

    if stripe_account.verification_status != "verified":
        raise APIError(APIError.STRIPE, f"Stripe account not verified")

    external_accounts = stripe.Account.list_external_accounts(
        stripe_account.account_id, api_key=Config.LIVE_STRIPE_KEY
    )

    existing_accounts = {
        account.external_id for account
        in AccountFactory.get_creator_stripe_bank_accounts(context.creator, context.cur)
    }

    result = {}
    for account in external_accounts:
        if account.object != "bank_account" or account.id in existing_accounts:
            continue

        result[account.id] = BankAccountData(
            country=CountryCache.get_country_by_code(account.country).name,
            account_holder_type='company',
            account_holder_name='TransferMole',
            bank_name=account.bank_name,
            account_number=f"***{account.last4}",
            currency=account.currency,
        )

    return result


@admin_router.post(
    path="/exchange_rates",
    operation_id="update_exchange_rates",
    response_model=None
)
async def admin_update_exchange_rates(
        context: Annotated[Context, Depends(required_access_token_ctx)],
        exchange_rates: Dict[str, Decimal],
) -> None:
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    Currency.set_exchange_rates(ExchangeRates(exchange_rates), context.cur)
    logger.info(f"Admin user {context.auth_account.username} changed exchange rates {exchange_rates}")


@admin_router.get(
    path="/providers",
    operation_id="get_provider_parameters",
    response_model=Dict[str, ProviderParameters]
)
async def admin_get_provider_parameters(
        context: Annotated[Context, Depends(required_access_token_ctx)],
) -> Dict[str, ProviderParameters]:
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    result: Dict[str, ProviderParameters] = {}
    for name, provider in PayoutProviders.CACHE.items():
        result[name] = provider.params

    return result


@admin_router.post(
    path="/providers",
    operation_id="update_provider_parameters",
    response_model=None
)
async def admin_update_provider_parameters(
        context: Annotated[Context, Depends(required_access_token_ctx)],
        providers_parameters: Dict[str, ProviderParameters],
) -> None:
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    for provider_name, params in providers_parameters.items():
        provider = PayoutProviders.get_provider(provider_name)
        provider.set_parameters(params, context.cur)


@admin_router.post(
    path="/verification/list_pending",
    operation_id="get_pending_verifications",
    response_model=List[InternalKYCHistory]
)
async def admin_get_pending_verifications(
        context: Annotated[Context, Depends(required_access_token_ctx)],
) -> List[InternalKYCHistory]:
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    return INTERNAL_KYC_PROVIDER.get_pending_verifications(context.cur)


class AddVerificationStepParams(BaseModel):
    creator_id: uuid.UUID
    verification_status: str
    message: Optional[str] = None


@admin_router.post(
    path="/verification",
    operation_id="add_verification_step",
    response_model=InternalKYCStep
)
async def admin_add_verification_step(
        params: AddVerificationStepParams,
        context: Annotated[Context, Depends(required_access_token_ctx)],
) -> InternalKYCStep:
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    return INTERNAL_KYC_PROVIDER.add_verification_step(
        params.creator_id, params.verification_status, params.message, context.cur
    )


class EventListParameters(BaseModel):
    category: Optional[EventCategory] = None
    creator_id: Optional[uuid.UUID] = None
    from_time: Optional[int] = None
    duration: Optional[Duration] = None


@admin_router.post(
    path="/events",
    operation_id="event_list",
    response_model=List[Notification]
)
async def event_list(
        context: Annotated[Context, Depends(required_access_token_ctx)],
        params: EventListParameters | None = None,
) -> List[Notification]:
    if context.auth_account.platform != "admin":
        raise APIError(
            APIError.ACCESS_ERROR,
            "Provided access token is not authorized to call admin methods"
        )

    from_time = datetime.fromtimestamp(params.from_time) if params and params.from_time else None
    duration = params.duration.to_timedelta() if params and params.duration else None
    return get_notifications(
        params.category if params else None,
        params.creator_id if params else None,
        from_time,
        duration,
        context.cur
    )
