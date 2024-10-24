from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from typing import Callable, Awaitable, Any
from stripe import StripeError
from contextlib import asynccontextmanager
import logging

from ...lib import init_transfer_mole
from ...lib.common.config import Config
from ...lib.common.database import Database
from ...lib.common.api_error import APIError
from ...lib.telegram.application import Application

logger = logging.getLogger(__name__)
logger.info("Starting API Service")
init_transfer_mole()

@asynccontextmanager
async def lifespan(application: Any):
    if 'telegram_webhook' in Config.ENABLED_APIS:
        logger.info("Init Telegram Application")
        Application.init(Config.TELEGRAM_BOT_TOKEN)
        await Application.start_webhook()

    # Lifespan startup
    yield

    if 'telegram_webhook' in Config.ENABLED_APIS:
        await Application.stop_webhook()
        logger.info("Telegram Application shutdown")


app = FastAPI(title="TransferMole", lifespan=lifespan)

@app.middleware("http")
async def api_method(request: Request, call_next:  Callable[[Request], Awaitable[Response]]) -> Response:
    cur = Database.begin()
    request.state.cursor = cur
    try:
        response: Response = await call_next(request)
        if response.status_code == 200:
            Database.commit()
        else:
            Database.rollback()
        return response
    except APIError as e:
        Database.rollback()
        logger.warning(f"{e.message}")
        match e.code:
            case APIError.OBJECT_NOT_FOUND:
                return JSONResponse(status_code=404, content={"error": e.message})
            case APIError.ACCESS_ERROR:
                return JSONResponse(status_code=403, content={"error": e.message})
            case _:
                return JSONResponse(status_code=500, content={"error": e.message})
    except StripeError as e:
        Database.rollback()
        logger.warning(f"Stripe error: {e}")
        msg = e.error.get('message', 'Unexpected error') if e.error else 'Unexpected error'
        return JSONResponse(status_code=500, content={"error": msg})
    except Exception as e:
        Database.rollback()
        logger.error(f"Exception: {e}")
        return JSONResponse(status_code=500, content={
            "error": "Internal error"
        })

########################################################################################################################
# API ROUTERS
########################################################################################################################

from ...lib.routers.links_api import router as links_router
app.include_router(router=links_router, prefix="/api")

if 'creator_api' in Config.ENABLED_APIS:
    logger.info(f"creator_api enabled")
    from ...lib.routers.creator_api import creator_router
    app.include_router(router=creator_router, prefix="/api")

if 'transfer_api' in Config.ENABLED_APIS:
    logger.info(f"transfer_api enabled")
    from ...lib.routers.transfer_api import transfer_router
    app.include_router(transfer_router, prefix="/api")

if 'admin_api' in Config.ENABLED_APIS:
    logger.info(f"admin_api enabled")
    from ...lib.routers.admin_api import admin_router
    app.include_router(admin_router, prefix="/api")

if 'settings_api' in Config.ENABLED_APIS:
    logger.info(f"settings_api enabled")
    from ...lib.routers.settings_api import router as settings_router
    app.include_router(settings_router, prefix="/api")

if 'circle_api' in Config.ENABLED_APIS:
    logger.info(f"circle_api enabled")
    from ...lib.routers.circle_api import circle_router
    app.include_router(router=circle_router, prefix="/api")
    
if 'telegram_api' in Config.ENABLED_APIS:
    logger.info(f"telegram_api enabled")
    from ...lib.routers.telegram_api import router as telegram_router
    app.include_router(telegram_router, prefix="/api")

if 'whack_a_mole' in Config.ENABLED_APIS:
    logger.info(f"Whack-a-mole enabled")
    from ...lib.routers.whack_a_mole_api import router as whack_a_mole_router
    app.include_router(router=whack_a_mole_router, prefix="/api")

if 'tasks_api' in Config.ENABLED_APIS:
    logger.info(f"Tasks API enabled")
    from ...lib.routers.tasks_api import router as tasks_router
    app.include_router(router=tasks_router, prefix="/api")

########################################################################################################################

if 'auth0_api' in Config.ENABLED_APIS:
    logger.info(f"auth0_api enabled")
    from ...lib.routers.auth0_api import router as auth0_router
    app.include_router(auth0_router)

if 'manychat_api' in Config.ENABLED_APIS:
    logger.info(f"manychat_api enabled")
    from ...lib.routers.manychat_instagram_api import router as manychat_instagram_router
    from ...lib.routers.manychat_whatsapp_api import router as manychat_whatsapp_router
    app.include_router(manychat_instagram_router)
    app.include_router(manychat_whatsapp_router)

########################################################################################################################
# WEBHOOK ROUTERS
########################################################################################################################

if 'stripe_webhook' in Config.ENABLED_APIS:
    logger.info(f"stripe_webhook enabled")
    from ...lib.routers.stripe_webhook import router as stripe_webhook_router
    app.include_router(router=stripe_webhook_router, prefix="/webhooks")

if 'circle_webhook' in Config.ENABLED_APIS:
    logger.info(f"circle_webhook enabled")
    from ...lib.routers.circle_webhook import router as circle_webhook_router
    app.include_router(router=circle_webhook_router, prefix="/webhooks")

if 'sumsub_webhook' in Config.ENABLED_APIS:
    logger.info(f"sumsub_webhook enabled")
    from ...lib.routers.sumsub_webhook import router as sumsub_webhook_router
    app.include_router(router=sumsub_webhook_router, prefix="/webhooks")

if 'mercuryo_webhook' in Config.ENABLED_APIS:
    logger.info(f"mercuryo_webhook enabled")
    from ...lib.routers.mercuryo_webhook import router as mercuryo_webhook_router
    app.include_router(router=mercuryo_webhook_router, prefix="/webhooks")

if 'telegram_webhook' in Config.ENABLED_APIS:
    logger.info(f"telegram_webhook enabled")
    from ...lib.routers.telegram_webhook import router as telegram_webhook_router
    app.include_router(router=telegram_webhook_router, prefix="/webhooks")


########################################################################################################################

Instrumentator().instrument(app).expose(app, tags=["metrics"])
