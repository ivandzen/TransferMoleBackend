from ...lib import init_transfer_mole

init_transfer_mole()

import asyncio
from .transaction_monitor import TransactionMonitor

monitor = TransactionMonitor()
asyncio.run(monitor.run())
