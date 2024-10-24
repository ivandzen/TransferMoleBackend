from ...lib.common.config import Config
from ...lib import init_transfer_mole
from ...lib.telegram.application import Application

init_transfer_mole()
Application.init(Config.TELEGRAM_BOT_TOKEN)
Application.run_polling()
