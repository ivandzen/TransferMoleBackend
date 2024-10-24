import logging
import time

from web3 import Web3, HTTPProvider
from decimal import Decimal
from web3.types import HexStr, BlockNumber, TxData, TxReceipt
from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, Optional, List, Literal, get_args, ItemsView

from .common.config import Config
from .common.api_error import APIError


TRANSFER_METHOD_ID = "a9059cbb"

logger = logging.getLogger(__name__)
CRYPTO_NETWORK_NAMES = Literal["Polygon", "Ethereum", "Avalanche C-Chain", "Base", "BSC"]
CRYPTO_PAYMENT_TYPES = [f"crypto:{network_name}" for network_name in get_args(CRYPTO_NETWORK_NAMES)]


class CryptoCurrency(BaseModel):
    decimals: int
    contract_address: Optional[str] = None


class CryptoNetwork(BaseModel):
    name: str
    chain_id: Optional[int] = None
    wallet_connect_id: str
    currencies: Dict[str, CryptoCurrency]
    tx_explorer_prefix: str
    rpc_urls: List[str]

    def update_latest_block(self) -> None:
        raise RuntimeError("CryptoNetwork.update_latest_block")

    def check_wallet_address(self, _address: str) -> str:
        raise RuntimeError("CryptoNetwork.check_wallet_address")

    def check_transaction(
            self, _tx_id: str, _exp_dst: str, _exp_curr_name: str, _exp_amount: Decimal
    ) -> None:
        raise RuntimeError("CryptoNetwork.check_transaction")

    def check_contract_address(self, _address: str) -> str:
        raise RuntimeError("CryptoNetwork.check_contract_address")

    def create_transaction(self, destination: str, currency_name: str, amount: Decimal) -> dict:
        raise RuntimeError(f"CryptoNetwork.create_transaction")

    def get_transaction_status(self, tx_id: str) -> str:
        raise RuntimeError(f"CryptoNetwork.get_transaction_status")

    def compare_addresses(self, addr1: str, addr2: str) -> bool:
        raise RuntimeError(f"CryptoNetwork.compare_addresses")


CHAIN_RETRY_INTERVAL_SEC = 5
CHAIN_NUM_RETRIES = 10


class EthereumLikeNetwork(CryptoNetwork):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    num_confirmations: int
    latest_block: Optional[BlockNumber] = Field(default=None, exclude=True)
    web3: Web3 = Field(exclude=True)

    def update_latest_block(self) -> None:
        self.latest_block = self.web3.eth.block_number
        logger.debug(f"Latest block {self.name} : {self.latest_block}")

    @staticmethod
    def _check_hex(address: str) -> bool:
        for ch in address.lower():
            if ch not in '0123456789abcdef':
                return False
        return True

    def check_wallet_address(self, address: str) -> str:
        if len(address) != 42 or address[:2] != '0x' or not self._check_hex(address[2:]):
            err_msg = f"Address must be 20 bytes hex encoded string with 0x prefix but got {address}"
            logger.warning(err_msg)
            raise APIError(APIError.WRONG_WALLET_ADDR, err_msg)
        return address.lower()

    def get_transaction(self, tx_id: str) -> TxData:
        if len(tx_id) != 66 or tx_id[:2] != '0x' or not self._check_hex(tx_id[2:]):
            err_msg = f"Transaction ID must be 32 bytes hex encoded string with 0x prefix but got {tx_id}"
            logger.warning(err_msg)
            raise APIError(APIError.WRONG_TXID, err_msg)

        num_retries = CHAIN_NUM_RETRIES
        while num_retries > 0:
            try:
                return self.web3.eth.get_transaction(HexStr(tx_id))
            except Exception as e:
                logger.warning(
                    f"eth_getTransactionByHash({HexStr(tx_id)}): {e}."
                    f"Will retry in {CHAIN_RETRY_INTERVAL_SEC} seconds ({num_retries} remaining)"
                )
                time.sleep(CHAIN_RETRY_INTERVAL_SEC)
                num_retries -= 1

        raise APIError(APIError.TRX_CHECK_ERROR, f"Unable to find transaction {tx_id}")

    def _get_transaction_receipt(self, tx_id: str) -> TxReceipt:
        num_retries = CHAIN_NUM_RETRIES
        while num_retries > 0:
            try:
                return self.web3.eth.get_transaction_receipt(HexStr(tx_id))
            except Exception as e:
                logger.warning(
                    f"eth_getTransactionReceipts({HexStr(tx_id)}): {e}."
                    f"Will retry in {CHAIN_RETRY_INTERVAL_SEC} seconds ({num_retries} remaining)"
                )
                time.sleep(CHAIN_RETRY_INTERVAL_SEC)
                num_retries -= 1

        raise APIError(APIError.TRX_CHECK_ERROR, f"Unable to get transaction receipt {tx_id}")

    def check_transaction(
            self, tx_id: str, exp_dst: str, exp_curr_name: str, exp_amount: Decimal
    ) -> None:
        exp_currency = self.currencies.get(exp_curr_name, None)
        if exp_currency is None:
            msg = f"Unknown currency {exp_curr_name}"
            logger.warning(msg)
            raise APIError(APIError.UNKNOWN_CURRENCY, msg)

        try:
            amount_dec = exp_amount * (10 ** exp_currency.decimals)
        except Exception as e:
            logger.info(f"Failed to parse int from amount {exp_amount}: {e}")
            raise APIError(
                APIError.WRONG_PARAMETERS,
                "Unable to decode transaction amount. "
                "Please, contact customer support"
            )

        transaction = self.get_transaction(tx_id)
        receipt = self._get_transaction_receipt(tx_id)
        if receipt.status == 0:
            raise APIError(APIError.TRX_CHECK_ERROR, "Transaction failed")

        to = transaction.get('to', None)
        if not to:
            raise APIError(APIError.TRX_CHECK_ERROR, "Transaction to field is empty")

        if exp_currency.contract_address is None:
            amount = Decimal(transaction.get('value', 0))
            if to != exp_dst:
                logger.warning(f"Expected destination {exp_dst} but got {to}")
                raise APIError(APIError.TRX_CHECK_ERROR, f"Transaction destination does not match")

            if amount_dec != amount:
                raise APIError(
                    APIError.TRX_CHECK_ERROR,
                    f"Transaction amount not match. Expected {amount_dec}, but got {amount}"
                )
        else:
            if to.lower() != exp_currency.contract_address.lower():
                raise APIError(APIError.TRX_CHECK_ERROR, f"Transaction contract address is not correct")

            trx_data = transaction.get('input', None)
            if len(trx_data) != 68:
                raise APIError(APIError.TRX_CHECK_ERROR, f"Transaction data expected to be 68 bytes long")

            if trx_data[0:4].hex().lower() != f'0x{TRANSFER_METHOD_ID}'.lower():
                raise APIError(APIError.TRX_CHECK_ERROR, f"Expected ERC-20 transfer method")

            actual_dst = f'0x{trx_data[16:36].hex().lower()}'
            if actual_dst == exp_dst.lower():
                logger.warning(f"Expected destination {exp_dst} but got {actual_dst}")
                raise APIError(APIError.TRX_CHECK_ERROR, f"Transaction destination does not match")

            amount = int(trx_data[36:].hex(), 16)
            if amount_dec != amount:
                raise APIError(
                    APIError.TRX_CHECK_ERROR,
                    f"Transaction amount not match. Expected {amount_dec}, but got {amount}"
                )

    def check_contract_address(self, address: str) -> str:
        return self.check_wallet_address(address)

    def create_transaction(self, destination: str, currency_name: str, amount: Decimal) -> dict:
        currency = self.currencies.get(currency_name, None)
        if currency is None:
            raise APIError(APIError.PAYMENT, f"Currency '{currency_name}' not supported")

        try:
            amount_int = int(amount * pow(10, currency.decimals))
            if amount_int < 0:
                raise APIError(APIError.PAYMENT, f"Amount must be >= 0")
        except Exception as e:
            logger.warning(e)
            raise APIError(APIError.PAYMENT, f"Wrong amount {amount}")

        contract_address = currency.contract_address
        if contract_address is None:
            transaction = {
                'to': destination,
                'value': hex(amount_int),
                'chainId': self.chain_id
            }
        else:
            transaction = {
                'to': contract_address,
                'data': f"0x{TRANSFER_METHOD_ID}"
                        f"{destination[2:].zfill(64)}{hex(amount_int)[2:].zfill(64)}",
                'chainId': self.chain_id
            }

        return transaction

    def get_transaction_status(self, tx_id: str) -> str:
        if not self.latest_block:
            return "pending"

        try:
            transaction = self.get_transaction(tx_id)
        except Exception as _:
            return "failed"

        block_number = transaction.get('blockNumber', None)
        if block_number is None:
            logger.error(f"{self.name} {tx_id} Unable to read blockNumber")
            return "pending"

        block_hash = transaction.get('blockHash', None)
        if block_hash is None:
            logger.info(f"{self.name} {tx_id} Rejected")
            return "failed"

        trx_confirmations = self.latest_block - block_number
        logger.debug(f"{self.name} {tx_id} - {trx_confirmations} confirmations")
        if trx_confirmations >= self.num_confirmations:
            return "confirmed"
        else:
            return "pending"

    def compare_addresses(self, addr1: str, addr2: str) -> bool:
        return addr1.lower() == addr2.lower()


def create_ethereum_network(rpc_url: str) -> EthereumLikeNetwork:
    return EthereumLikeNetwork(
        name="Ethereum", chain_id=1, wallet_connect_id='eip155:1',
        currencies={
            #'ETH': CryptoCurrency(decimals=18, contract_address=None),
            #'USDT': CryptoCurrency(decimals=6, contract_address='0xdAC17F958D2ee523a2206206994597C13D831ec7'),
            'USDC': CryptoCurrency(decimals=6, contract_address='0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'),
        },
        num_confirmations=12,
        tx_explorer_prefix="https://etherscan.io/tx/",
        rpc_urls=[
            "https://eth.llamarpc.com",
            "https://eth.meowrpc.com",
            "https://eth.nodeconnect.org",
            "https://rpc.flashbots.net",
        ],
        web3=Web3(HTTPProvider(rpc_url)),
    )


def create_polygon_network(rpc_url: str) -> EthereumLikeNetwork:
    return EthereumLikeNetwork(
        name="Polygon", chain_id=137, wallet_connect_id='eip155:137',
        currencies={
            #'MATIC': CryptoCurrency(decimals=18, contract_address=None),
            #'WETH': CryptoCurrency(decimals=18, contract_address='0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619'),
            #'USDT': CryptoCurrency(decimals=6, contract_address='0xc2132D05D31c914a87C6611C10748AEb04B58e8F'),
            'USDC': CryptoCurrency(decimals=6, contract_address='0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359'),
        },
        num_confirmations=200,
        tx_explorer_prefix="https://polygonscan.com/tx/",
        rpc_urls=[
            "https://polygon.llamarpc.com",
            "https://polygon.meowrpc.com",
            "https://polygon.drpc.org",
            "https://polygon-pokt.nodies.app"
        ],
        web3=Web3(HTTPProvider(rpc_url)),
    )


def create_avalanche_network(rpc_url: str) -> EthereumLikeNetwork:
    return EthereumLikeNetwork(
        name="Avalanche C-Chain", chain_id=43114, wallet_connect_id='eip155:43114',
        currencies={
            #'WAVAX': CryptoCurrency(decimals=18, contract_address='0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7'),
            #'WETH': CryptoCurrency(decimals=18, contract_address='0x49D5c2BdFfac6CE2BFdB6640F4F80f226bc10bAB'),
            #'USDT': CryptoCurrency(decimals=6, contract_address='0xde3A24028580884448a5397872046a019649b084'),
            'USDC': CryptoCurrency(decimals=6, contract_address='0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E'),
            'VSO': CryptoCurrency(decimals=18, contract_address='0x846D50248BAf8b7ceAA9d9B53BFd12d7D7FBB25a'),
        },
        num_confirmations=20,
        tx_explorer_prefix="https://avascan.info/blockchain/c/tx/",
        rpc_urls=[
            "https://rpc.ankr.com/avalanche",
            "https://avalanche.drpc.org",
            "https://avalanche-c-chain-rpc.publicnode.com",
            "https://avax-pokt.nodies.app/ext/bc/C/rpc"
        ],
        web3=Web3(HTTPProvider(rpc_url)),
    )


def create_base_network(rpc_url: str) -> EthereumLikeNetwork:
    return EthereumLikeNetwork(
        name="Base", chain_id=8453, wallet_connect_id='eip155:8453',
        currencies={
            'USDC': CryptoCurrency(decimals=6, contract_address='0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'),
        },
        num_confirmations=20,
        tx_explorer_prefix="https://basescan.org/tx/",
        rpc_urls=[
            "https://base.drpc.org",
        ],
        web3=Web3(HTTPProvider(rpc_url)),
    )


def create_bsc_network(rpc_url: str) -> EthereumLikeNetwork:
    return EthereumLikeNetwork(
        name="BSC", chain_id=56, wallet_connect_id='eip155:56',
        currencies={
            'USDC': CryptoCurrency(decimals=18, contract_address='0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d'),
        },
        num_confirmations=20,
        tx_explorer_prefix="https://bscscan.com/tx/",
        rpc_urls=[
            "https://rpc.ankr.com/bsc",
        ],
        web3=Web3(HTTPProvider(rpc_url)),
    )


class CryptoNetworks:
    NETWORKS: Optional[Dict[str, CryptoNetwork]] = None

    @staticmethod
    def init() -> None:
        logger.info(f"Initializing CryptoNetworks module...")
        CryptoNetworks.NETWORKS = {
            "Ethereum": create_ethereum_network(Config.ETHEREUM_RPC),
            "Polygon": create_polygon_network(Config.POLYGON_RPC),
            "Avalanche C-Chain": create_avalanche_network(Config.AVALANCHE_CCHAIN_RPC),
            "Base": create_base_network(Config.BASE_BLOCKCHAIN_RPC),
            "BSC": create_bsc_network(Config.BSC_BLOCKCHAIN_RPC),
        }
        logger.info(f"Available networks are: {CryptoNetworks.NETWORKS.keys()}")

    @staticmethod
    def get(name: str) -> CryptoNetwork:
        if CryptoNetworks.NETWORKS is None:
            logger.error("CryptoNetworks not initialized")
            raise APIError(APIError.INTERNAL)

        network = CryptoNetworks.NETWORKS.get(name, None)
        if not network:
            raise APIError(
                APIError.OBJECT_NOT_FOUND,
                f"Unsupported crypto network: {name}"
            )

        return network

    @staticmethod
    def items() -> ItemsView[str, CryptoNetwork]:
        if CryptoNetworks.NETWORKS is None:
            logger.error("CryptoNetworks not initialized")
            raise APIError(APIError.INTERNAL)

        return CryptoNetworks.NETWORKS.items()
