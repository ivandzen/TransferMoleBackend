import datetime
import uuid
import logging
from psycopg2.extensions import cursor
from decimal import Decimal
from pydantic import BaseModel, field_serializer
from typing import List, Optional, Dict, Tuple, Any

from .payment import Payment
from .common.api_error import APIError
from .authentication.auth_account import AuthAccount, AuthAccountData, PlatformType
from .authentication.auth_account_factory import construct_auth_account
from .payout.payment_intent import PaymentData

logger = logging.getLogger(__name__)


class Transfer(BaseModel):
    transfer_id: uuid.UUID
    creator_id: uuid.UUID
    sender: Optional[uuid.UUID] = None
    message: Optional[str] = None
    payments: List[Payment]
    started_at: datetime.datetime
    status: str
    remittance_user: Optional[uuid.UUID] = None
    tm_fee: Optional[Decimal] = None
    auth_account: Optional[AuthAccount] = None

    @field_serializer('started_at')
    def serialize_started_at(self, started_at: datetime.datetime, _info: Any) -> int:
        return int(started_at.timestamp() * 1000)

    @staticmethod
    def _run_query(query_ending: str, params: tuple, cur: cursor) -> Dict[uuid.UUID, 'Transfer']:
        cur.execute(
            f"SELECT "
            # Transfer columns
            "   t.transfer_id, t.creator_id, t.sender, t.message, t.started_at, t.status, t.remittance_user, t.tm_fee, "
            # Payment columns
            "   p.payment_index, p.sender_channel_id, p.payout_channel_id, p.payment_type, p.provider, p.currency, "
            "   p.external_id, p.total_amount, p.to_usd_rate, p.provider_fee, p.payment_data, p.status, "
            "   p.creation_time, "
            # Auth account columns
            "   aa.account_id, aa.platform, aa.userid, aa.username, aa.creator_id, aa.account_data, "
            "   aa.notifications, aa.password_hashed, aa.password_salt, aa.current_state "
            "FROM public.transfer AS t "
            "INNER JOIN public.payment AS p "
            "   ON t.transfer_id = p.transfer_id "
            "LEFT JOIN public.auth_account AS aa "
            "   ON t.auth_account = aa.account_id "
            f"{query_ending}",
            params
        )
        auth_accounts: Dict[PlatformType, AuthAccount] = {}
        result: Dict[uuid.UUID, 'Transfer'] = {}
        for entry in cur:
            auth_account = None
            if entry[21] is not None:
                account_data = AuthAccountData.model_validate_json(entry[26]) if entry[26] else None
                platform = entry[22]
                password_hased = bytes(entry[28]) if entry[28] else None
                password_salt = bytes(entry[29]) if entry[29] else None
                auth_account = auth_accounts.setdefault(platform, construct_auth_account(
                    account_id=entry[21], platform=platform, userid=entry[23], username=entry[24],
                    creator_id=entry[25], account_data=account_data, notifications=entry[27],
                    password_hashed=password_hased, password_salt=password_salt, current_state=entry[30],
                ))

            transfer_id = entry[0]
            payment_data = PaymentData.model_validate_json(entry[18]) if entry[18] is not None else None
            result.setdefault(
                transfer_id,
                Transfer(
                    transfer_id=transfer_id, creator_id=entry[1], sender=entry[2], message=entry[3], payments=[],
                    started_at=entry[4], status=entry[5], remittance_user=entry[6], tm_fee=entry[7],
                    auth_account=auth_account,
                )
            ).payments.append(
                Payment(
                    transfer_id=transfer_id, payment_index=entry[8], sender_channel_id=entry[9],
                    payout_channel_id=entry[10], payment_type=entry[11], provider=entry[12], currency=entry[13],
                    external_id=entry[14], total_amount=entry[15], to_usd_rate=entry[16], provider_fee=entry[17],
                    payment_data=payment_data, status=entry[19], creation_time=entry[20],
                )
            )

        return result

    @staticmethod
    def create_new(
            creator_id: uuid.UUID,
            sender: uuid.UUID | None,
            message: str | None,
            remittance_user: uuid.UUID | None,
            auth_account: AuthAccount | None,
            tm_fee: Decimal | None,
            cur: cursor
    ) -> 'Transfer | None':
        cur.execute(
            "INSERT INTO public.transfer("
            "   creator_id, sender, message, remittance_user, tm_fee, auth_account"
            ") "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "RETURNING transfer_id, started_at, status;",
            (
                creator_id, sender, message, remittance_user, tm_fee,
                auth_account.account_id if auth_account else None,
            )
        )

        result = cur.fetchone()
        if result is None:
            return None

        transfer_id = result[0]
        started_at = result[1]
        return Transfer(
            transfer_id=transfer_id, creator_id=creator_id, sender=sender, message=message, payments=[],
            started_at=started_at, status=result[2], remittance_user=remittance_user, tm_fee=tm_fee,
            auth_account=auth_account,
        )

    @staticmethod
    def get_by_id(transfer_id: uuid.UUID, cur: cursor) -> 'Transfer':
        result = Transfer._run_query(
            query_ending="WHERE t.transfer_id = %s ORDER BY p.payment_index;",
            params=(transfer_id,),
            cur=cur
        )

        for _, entry in result.items():
            return entry

        raise APIError(APIError.OBJECT_NOT_FOUND, f"Transfer {str(transfer_id)} not found")

    def set_tm_fee(self, tm_fee: Decimal, cur: cursor) -> None:
        cur.execute(
            "UPDATE public.transfer SET tm_fee = %s WHERE transfer_id = %s;",
            (tm_fee, self.transfer_id,)
        )

    def set_status(self, status: str, cur: cursor) -> None:
        cur.execute(
            f"UPDATE public.transfer SET status = %s WHERE transfer_id = %s;",
            (status, self.transfer_id,)
        )

    def create_payment(
            self,
            payment_type: str,
            currency: str,
            sender_channel_id: uuid.UUID | None,
            recipient_channel_id: uuid.UUID,
            provider: str,
            cur: cursor
    ) -> Payment:
        new_payment = Payment.create_new(
            transfer_id=self.transfer_id,
            payment_index=len(self.payments),
            payment_type=payment_type,
            currency=currency,
            sender_channel_id=sender_channel_id,
            recipient_channel_id=recipient_channel_id,
            provider=provider,
            cur=cur
        )

        self.payments.append(new_payment)
        return new_payment

    @staticmethod
    def get_transfers(
            creator_id: uuid.UUID | None,
            remittance_user: uuid.UUID | None,
            from_time: datetime.datetime | None,
            duration: datetime.timedelta | None,
            exclude_statuses: list[str],
            cur: cursor
    ) -> Dict[uuid.UUID, 'Transfer']:
        query_ending = "WHERE t.status <> 'created' "
        params: Tuple[Any, ...] = ()

        for exclude_status in exclude_statuses:
            query_ending += "AND t.status <> %s "
            params += (exclude_status,)

        if creator_id:
            query_ending += "AND (t.creator_id = %s OR t.sender = %s) "
            params += (creator_id, creator_id)

        if remittance_user:
            query_ending += "AND t.remittance_user = %s "
            params += (remittance_user,)

        if from_time:
            query_ending += "AND t.started_at >= %s "
            params += (from_time,)
            if duration:
                query_ending += "AND t.started_at <= %s "
                params += (from_time + duration,)

        query_ending += "ORDER BY t.started_at DESC, p.payment_index;"
        return Transfer._run_query(
            query_ending=query_ending,
            params=params,
            cur=cur,
        )
