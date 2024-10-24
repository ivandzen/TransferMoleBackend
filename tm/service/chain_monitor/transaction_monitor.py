import time
from psycopg2.extensions import cursor
import logging
import asyncio

from ...lib.crypto_network import CryptoNetwork, CryptoNetworks
from ...lib.common.database import Database
from ...lib.payment import Payment
from ...lib.payment_processor import update_payment
from ...lib.payout.providers.payout_provider_cache import PROVIDER_POLYGON, PROVIDER_ETHEREUM, PROVIDER_AVALANCHE, \
    PROVIDER_BASE, PROVIDER_BSC

logger = logging.getLogger(__name__)


class TransactionMonitor:
    def _process_pending_payment(self, network: CryptoNetwork, payment: Payment, cur: cursor) -> None:
        if payment.external_id is None:
            logger.debug(
                f"Payment {payment.transfer_id}:{payment.payment_index} "
                f"- external id is not set"
            )
            return

        trx_status = network.get_transaction_status(payment.external_id)
        if trx_status == "confirmed":
            update_payment(payment, cur, status='paid out')
        elif trx_status == "rejected":
            update_payment(payment, cur, status='rejected')

    def process_network(self, network_name: str, cur: cursor) -> None:
        pending_payments = Payment.get_submitted_crypto_payments(network_name, cur)
        if len(pending_payments) > 0:
            network = CryptoNetworks.get(network_name)
            network.update_latest_block()
            for payment in pending_payments:
                self._process_pending_payment(network, payment, cur)

    def _iteration(self, cur: cursor) -> None:
        self.process_network(PROVIDER_POLYGON.name, cur)
        self.process_network(PROVIDER_ETHEREUM.name, cur)
        self.process_network(PROVIDER_AVALANCHE.name, cur)
        self.process_network(PROVIDER_BASE.name, cur)
        self.process_network(PROVIDER_BSC.name, cur)

    async def run(self) -> None:
        while True:
            try:
                cur = Database.begin()
                self._iteration(cur)
                Database.commit()
            except Exception as e:
                logger.warning(e.__str__())

            await asyncio.sleep(30)
