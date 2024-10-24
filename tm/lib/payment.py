import uuid
from psycopg2.extensions import cursor
import datetime
import json
import logging
from decimal import Decimal
from pydantic import BaseModel, model_validator, field_serializer
from typing import Optional, Tuple, Any

from .common.api_error import APIError
from .payout.payment_intent import PaymentData

logger = logging.getLogger(__name__)


class UpdatePaymentParams(BaseModel):
    status: Optional[str] = None
    payment_data: Optional[PaymentData] = None
    external_id: Optional[str] = None
    total_amount: Optional[Decimal] = None
    to_usd_rate: Optional[Decimal] = None
    provider_fee: Optional[Decimal] = None

    @model_validator(mode="after")
    def validate_self(self) -> 'UpdatePaymentParams':
        if self.total_amount:
            if not self.to_usd_rate:
                raise APIError(APIError.PAYMENT, f"to_usd rate must be specified")

        return self


class Payment(BaseModel):
    transfer_id: uuid.UUID
    payment_index: int
    sender_channel_id: Optional[uuid.UUID] = None
    payout_channel_id: uuid.UUID
    payment_type: str
    provider: str
    external_id: Optional[str] = None
    currency: str
    total_amount: Optional[Decimal] = None
    to_usd_rate: Optional[Decimal] = None
    provider_fee: Optional[Decimal] = None
    payment_data: Optional[PaymentData] = None
    status: str
    creation_time: datetime.datetime

    @field_serializer('creation_time')
    def serialize_creation_time(self, creation_time: datetime.datetime, _info: Any) -> int:
        return int(creation_time.timestamp() * 1000)

    @staticmethod
    def create_new(
            transfer_id: uuid.UUID, payment_index: int, payment_type: str, currency: str,
            sender_channel_id: uuid.UUID | None, recipient_channel_id: uuid.UUID, provider: str, cur: cursor
    ) -> 'Payment':
        cur.execute(
            f"INSERT INTO public.payment "
            f"(transfer_id, payment_index, sender_channel_id, "
            f"payout_channel_id, payment_type, provider, currency) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING  status, creation_time;",
            (transfer_id, payment_index, sender_channel_id, recipient_channel_id, payment_type, provider, currency),
        )

        result = cur.fetchone()
        if result is None:
            logger.warning(f"Payment not created")
            raise APIError(APIError.PAYMENT, f"Failed to create payment")

        status, creation_time = result[0], result[1]
        return Payment(
            transfer_id=transfer_id, payment_index=payment_index, sender_channel_id=sender_channel_id,
            payout_channel_id=recipient_channel_id, payment_type=payment_type, provider=provider, currency=currency,
            external_id=None, total_amount=None, to_usd_rate=None, provider_fee=None, payment_data=None, status=status,
            creation_time=creation_time,
        )

    @staticmethod
    def load(transfer_id: uuid.UUID, payment_index: int, cur: cursor) -> 'Payment':
        logger.debug(f"Loading Payment {transfer_id}:{payment_index}")
        cur.execute(
            f"SELECT "
            f"transfer_id, payment_index, sender_channel_id, payout_channel_id, payment_type, provider, currency, "
            f"external_id, total_amount, to_usd_rate, provider_fee, payment_data, status, creation_time "
            f"FROM public.payment "
            f"WHERE transfer_id = %s AND payment_index = %s;",
            (transfer_id, payment_index,)
        )

        result = cur.fetchone()
        if result is None:
            raise APIError(APIError.PAYMENT, f"Payment not found")

        payment_data = PaymentData.model_validate_json(result[11]) if result[11] is not None else None
        return Payment(
            transfer_id=result[0], payment_index=result[1], sender_channel_id=result[2], payout_channel_id=result[3],
            payment_type=result[4], provider=result[5], currency=result[6], external_id=result[7],
            total_amount=result[8], to_usd_rate=result[9], provider_fee=result[10], payment_data=payment_data,
            status=result[12], creation_time=result[13],
        )

    @staticmethod
    def get_submitted_crypto_payments(network: str, cur: cursor) -> list['Payment']:
        cur.execute(
            "SELECT "
            "transfer_id, payment_index, sender_channel_id, payout_channel_id, payment_type, provider, currency, "
            "external_id, total_amount, to_usd_rate, provider_fee, payment_data, status, "
            "creation_time "
            "FROM public.payment "
            "WHERE "
            f"   payment_type = 'crypto:{network}' AND status = 'submitted';",
        )

        result = []
        for entry in cur:
            payment_data = PaymentData.model_validate_json(entry[11]) if entry[11] is not None else None
            result.append(
                Payment(
                    transfer_id=entry[0], payment_index=entry[1], sender_channel_id=entry[2], payout_channel_id=entry[3],
                    payment_type=entry[4], provider=entry[5], currency=entry[6], external_id=entry[7],
                    total_amount=entry[8], to_usd_rate=entry[9], provider_fee=entry[10], payment_data=payment_data,
                    status=entry[12], creation_time=entry[13],
                )
            )
        return result

    @staticmethod
    def stripe_payment_intents_completed(payment_intents: list[str], cur: cursor) -> None:
        cur.execute(
            f"UPDATE public.payment "
            f"SET status = 'paid out' "
            f"WHERE payment_type = 'card' AND provider='Stripe' AND status <> 'paid out' AND external_id = ANY(%s);",
            (payment_intents,)
        )

    @staticmethod
    def get_stripe_payment_by_checkout_session(checkout_session: str, cur: cursor) -> 'Payment':
        cur.execute(
            f"SELECT "
            # Payment parameters
            "transfer_id, payment_index, sender_channel_id, payout_channel_id, payment_type, provider, currency, "
            "external_id, total_amount, to_usd_rate, provider_fee, payment_data, status, creation_time "
            "FROM public.payment "
            "WHERE payment_type = 'card' AND provider='Stripe' AND external_id = %s;",
            (checkout_session,)
        )

        result = cur.fetchone()
        if result is None:
            raise APIError(
                APIError.INTERNAL,
                f"Payment not found for checkout session: {checkout_session}"
            )

        payment_data = PaymentData.model_validate_json(result[11]) if result[11] is not None else None
        return Payment(
            transfer_id=result[0], payment_index=result[1], sender_channel_id=result[2], payout_channel_id=result[3],
            payment_type=result[4], provider=result[5], currency=result[6], external_id=result[7],
            total_amount=result[8], to_usd_rate=result[9], provider_fee=result[10], payment_data=payment_data,
            status=result[12], creation_time=result[13],
        )

    def update(self, update_params: UpdatePaymentParams, cur: cursor) -> None:
        args: Tuple[Any, ...] = ()
        query = "UPDATE public.payment SET "
        has_arguments = False
        for key, value in iter(update_params):
            if value is not None:
                self.__dict__[key] = value
                query += f"{key} = %s,"
                has_arguments = True
                if isinstance(value, dict):
                    args = args + (json.dumps(value),)
                elif isinstance(value, BaseModel):
                    args = args + (value.model_dump_json(),)
                else:
                    args = args + (value,)

        if not has_arguments:
            return

        query = query[:-1]
        query += " WHERE transfer_id = %s AND payment_index = %s;"
        cur.execute(
            query,
            args + (self.transfer_id, self.payment_index,)
        )
