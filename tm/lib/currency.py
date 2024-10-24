import logging
import re
from decimal import Decimal
from psycopg2.extensions import cursor
from pydantic import RootModel, model_validator
from typing import Dict, Any, Generator, Tuple

from .common.api_error import APIError
from .redis_cache import CachedObject

logger = logging.getLogger(__name__)
CURRENCY_SYMBOL_REGEXP = re.compile("^[A-Z]+$")


class ExchangeRates(RootModel):
    root: Dict[str, Decimal]

    @model_validator(mode="after")
    def validate_self(self) -> 'ExchangeRates':
        for symbol, _ in self.root.items():
            if not CURRENCY_SYMBOL_REGEXP.match(symbol.upper()):
                raise APIError(APIError.INTERNAL, f"Wrong currency: {symbol}")

        return self

    def __iter__(self) -> Any:
        return iter(self.root)

    def __getitem__(self, item: str) -> Decimal:
        return self.root[item]

    def get(self, key: str, default: Any) -> Any:
        return self.root.get(key, default)


CachedExchangeRates = CachedObject[ExchangeRates]


def check_amount(amount: Decimal) -> None:
    if amount < 0:
        raise APIError(
            APIError.WRONG_PARAMETERS,
            f"Amount must be > 0"
        )


class Currency:
    EXCHANGE_RATES: CachedExchangeRates | None = None

    @staticmethod
    def check_currency_symbol(symbol: str) -> None:
        if not Currency.EXCHANGE_RATES:
            raise APIError(APIError.INTERNAL, f"Currency cache not initialized")

        if not Currency.EXCHANGE_RATES.get(symbol, None):
            raise APIError(
                APIError.UNKNOWN_CURRENCY,
                f"Currency {symbol} is not supported"
            )

    @staticmethod
    def update_cache(cur: cursor) -> None:
        logger.info(f"Initializing Currency cache...")
        cur.execute(
            f"SELECT symbol, to_usd FROM public.currency;"
        )

        rates = {}
        for entry in cur:
            symbol = entry[0].upper()
            to_usd = entry[1]
            check_amount(to_usd)
            rates[symbol] = to_usd
        logger.info(f"Total {len(rates)} currencies preloaded.")
        Currency.EXCHANGE_RATES = CachedExchangeRates(
            cache_key="ExchangeRates",
            cls=ExchangeRates,
            instance=ExchangeRates(root=rates)
        )

    @staticmethod
    def get_exchange_rate_to_usd(currency: str) -> Decimal:
        if currency.lower() == "usd":
            return Decimal(1.0)

        if not Currency.EXCHANGE_RATES:
            raise APIError(APIError.INTERNAL, f"Currency cache not initialized")
        
        result = Currency.EXCHANGE_RATES.get(currency.upper(), None)
        if not result:
            raise APIError(
                APIError.WRONG_PARAMETERS,
                f"Exchange rate for {currency.upper()} not found"
            )

        return result

    @staticmethod
    def get_exchange_rates() -> ExchangeRates:
        if not Currency.EXCHANGE_RATES:
            raise APIError(APIError.INTERNAL, f"Currency cache not initialized")

        Currency.EXCHANGE_RATES.refresh()
        return Currency.EXCHANGE_RATES.instance

    @staticmethod
    def set_exchange_rates(rates: ExchangeRates, cur: cursor) -> None:
        if not Currency.EXCHANGE_RATES:
            raise APIError(APIError.INTERNAL, f"Currency cache not initialized")

        query = "INSERT INTO public.currency(symbol, to_usd) VALUES"
        params: Tuple[Any, ...] = ()
        for symbol in rates:
            rate = rates[symbol]
            if not isinstance(symbol, str) or len(symbol) > 10:
                raise APIError(APIError.UNKNOWN_CURRENCY, f"wrong currency symbol {symbol}")

            if not isinstance(rate, Decimal):
                raise APIError(APIError.UNKNOWN_CURRENCY, f"wrong exchange rate for {symbol}")

            query += " (%s, %s),"
            params += (symbol, rate)

        query = query[:-1]
        query += " ON CONFLICT (symbol) DO UPDATE SET to_usd=excluded.to_usd;"
        cur.execute(query, params)
        Currency.EXCHANGE_RATES.instance.root.update(rates.root)
        Currency.EXCHANGE_RATES.upload()


def convert_usd_to_currency(amount_usd: Decimal, target_currency: str) -> Decimal:
    exchange_rate = Currency.get_exchange_rate_to_usd(target_currency)
    return amount_usd / exchange_rate


def convert_currency_to_usd(amount: Decimal, source_currency: str) -> Decimal:
    exchange_rate = Currency.get_exchange_rate_to_usd(source_currency)
    return amount * exchange_rate
