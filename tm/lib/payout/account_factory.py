from psycopg2.extensions import cursor
import logging
from pydantic import BaseModel
from typing import Tuple, Any, Dict, List
import stripe
import uuid

from ..verification.stripe_account import StripeAccount
from ..verification.creator_verificator import VerificationStates
from ..common.api_error import APIError
from ..common.config import Config
from ..creator import Creator
from ..country_codes import get_country_by_code
from ..country import Country
from ..notification import AccountCreated
from ..notification_utils import send_notification
from .termination_account import TerminationAccount, PayoutChannelType, ProviderAccountType
from .stripe_bank_account import StripeBankAccountProviderData
from .bank_account import BankAccountData, BankPayoutChannel
from .crypto_account import CryptoAccountDetails, CryptoPayoutChannel
from .stripe_bank_account import StripeBankAccount
from .windapp_bank_account import WindappBankAccount
from .self_custody_crypto_wallet import SelfCustodyCryptoWallet
from .circle_crypto_wallet import CircleCryptoWallet
from .payout_channel import PayoutChannel
from .mercuryo_crypto_provider_account import MercuryoCryptoProviderAccount, MERCURYO_NETWORK_NAME
from .providers.payout_provider_cache import (PROVIDER_MERCURYO, PROVIDER_STRIPE, PROVIDER_WINDAPP, PROVIDER_CIRCLE,
                                              PROVIDER_AVALANCHE, PROVIDER_POLYGON, PROVIDER_ETHEREUM, PROVIDER_BASE,
                                              PROVIDER_BSC)
from ..verification.creator_verificator import CreatorVerificator

logger = logging.getLogger(__name__)
PAYOUT_CHANNEL_COLUMNS = "pc.creator_id, pc.channel_id, pc.type, pc.data, pc.currency, pc.removed"
PROVIDER_ACCOUNT_COLUMNS = "pa.provider, pa.provider_data, pa.external_id"
DEFAULT_COLUMN_LIST = f"{PAYOUT_CHANNEL_COLUMNS}, {PROVIDER_ACCOUNT_COLUMNS}"


def construct_bank_channel(entry: Tuple[Any, ...]) -> BankPayoutChannel:
    if entry[2] != "bank_account":
        raise APIError(APIError.INTERNAL, f"Payout channel {entry[1]} is not bank_account")

    if entry[3] is None:
        raise APIError(APIError.INTERNAL, f"Bank channel {entry[1]} has no data")

    return BankPayoutChannel(
        creator_id=entry[0],
        channel_id=entry[1],
        channel_type=entry[2],
        data=BankAccountData.model_validate_json(entry[3]),
        currency=entry[4],
        removed=entry[5],
    )


def construct_crypto_channel(entry: Tuple[Any, ...]) -> CryptoPayoutChannel:
    if entry[2] != "crypto":
        raise APIError(APIError.INTERNAL, f"Payout channel {entry[1]} is not crypto")

    if entry[3] is None:
        raise APIError(APIError.INTERNAL, f"Crypto channel {entry[1]} has no data")

    return CryptoPayoutChannel(
        creator_id=entry[0],
        channel_id=entry[1],
        channel_type=entry[2],
        data=CryptoAccountDetails.model_validate_json(entry[3]),
        currency=entry[4],
        removed=entry[5],
    )


class AvailablePayoutChannels(BaseModel):
    crypto: bool = False
    bank_account: bool = False
    stripe_bank_account: bool = False
    e_wallet: bool = False
    debit_card: bool = False


class AccountFactory:
    @staticmethod
    def _load_accounts(
            query: str,
            parameters: Tuple | None,
            verification_states: VerificationStates,
            cur: cursor
    ) -> Dict[uuid.UUID, TerminationAccount]:
        cur.execute(query, parameters)
        crypto_payout_channels: Dict[uuid.UUID, CryptoPayoutChannel] = {}
        bank_payout_channels: Dict[uuid.UUID, BankPayoutChannel] = {}
        result: Dict[uuid.UUID, TerminationAccount] = {}

        def add_provider_account(
                ch_id: uuid.UUID,
                pc: PayoutChannelType,
                pa: ProviderAccountType,
        ) -> None:
            result.setdefault(
                ch_id,
                TerminationAccount(
                    payout_channel=pc,
                    provider_accounts=[],
                )
            ).provider_accounts.append(pa)

        for entry in cur:
            channel_id = entry[1]
            channel_type = entry[2]
            provider = entry[6]
            external_id = entry[8]

            match channel_type:
                case "bank_account":
                    bank_payout_channel = bank_payout_channels.setdefault(
                        channel_id,
                        construct_bank_channel(entry)
                    )

                    match provider:
                        case PROVIDER_STRIPE.name:
                            add_provider_account(
                                channel_id,
                                bank_payout_channel,
                                StripeBankAccount.load(
                                    payout_channel=bank_payout_channel,
                                    verification_states=verification_states,
                                    provider_data=StripeBankAccountProviderData.model_validate_json(entry[7]) if entry[7] else None,
                                    external_id=external_id
                                )
                            )

                        case PROVIDER_WINDAPP.name:
                            add_provider_account(
                                channel_id,
                                bank_payout_channel,
                                WindappBankAccount.load(
                                    payout_channel=bank_payout_channel,
                                    verification_states=verification_states,
                                    external_id=external_id
                                )
                            )

                        case unknown:
                            logger.error(f"Bank account {bank_payout_channel.channel_id} has provider {unknown}")
                            raise APIError(
                                APIError.INTERNAL,
                                f"Unexpected error. Please, contact customer support"
                            )

                case "crypto":
                    crypto_payout_channel = crypto_payout_channels.setdefault(
                        channel_id,
                        construct_crypto_channel(entry)
                    )

                    match provider:
                        case PROVIDER_POLYGON.name | PROVIDER_ETHEREUM.name | PROVIDER_AVALANCHE.name | PROVIDER_BASE.name | PROVIDER_BSC.name:
                            add_provider_account(
                                channel_id,
                                crypto_payout_channel,
                                SelfCustodyCryptoWallet.load(payout_channel=crypto_payout_channel),
                            )

                        case PROVIDER_MERCURYO.name:
                            add_provider_account(
                                channel_id,
                                crypto_payout_channel,
                                MercuryoCryptoProviderAccount.load(
                                    payout_channel=crypto_payout_channel,
                                    verification_states=verification_states,
                                    external_id=external_id
                                )
                            )

                        case PROVIDER_CIRCLE.name:
                            add_provider_account(
                                channel_id,
                                crypto_payout_channel,
                                CircleCryptoWallet.load(
                                    payout_channel=crypto_payout_channel,
                                    external_id=external_id,
                                )
                            )

                        case unknown:
                            logger.error(f"Crypto account {crypto_payout_channel.channel_id} has provider {unknown}")
                            raise APIError(
                                APIError.INTERNAL,
                                f"Unexpected error. Please, contact customer support"
                            )

                case unknown:
                    logger.error(f"{unknown} channel type for payout channel {channel_id}")
                    continue

        return result

    @staticmethod
    def get_account(
            channel_id: uuid.UUID,
            cur: cursor,
            with_removed: bool = False,
            verification_states: VerificationStates = VerificationStates({}),
    ) -> TerminationAccount:
        tmp = AccountFactory._load_accounts(
            query=f"SELECT {DEFAULT_COLUMN_LIST} "
                  f"FROM public.payout_channel AS pc "
                  f"INNER JOIN public.provider_account AS pa "
                  f"ON pc.channel_id = pa.channel_id "
                  f"WHERE pc.channel_id = %s"
                  f"{' AND removed = False;' if not with_removed else ';'}",
            parameters=(channel_id,),
            verification_states=verification_states,
            cur=cur
        )

        for _, account_info in tmp.items():
            return account_info

        raise APIError(
            APIError.OBJECT_NOT_FOUND,
            f"Account {channel_id} not found"
        )

    @staticmethod
    def get_provider_account(
            channel_id: uuid.UUID,
            provider: str,
            verification_states: VerificationStates,
            cur: cursor,
    ) -> ProviderAccountType:
        tmp = AccountFactory._load_accounts(
            query=f"SELECT {DEFAULT_COLUMN_LIST} "
                  f"FROM public.payout_channel AS pc "
                  f"INNER JOIN public.provider_account AS pa "
                  f"ON pc.channel_id = pa.channel_id "
                  f"WHERE pc.channel_id = %s AND provider = %s;",
            parameters=(channel_id, provider),
            verification_states=verification_states,
            cur=cur
        )

        for _, term_acc in tmp.items():
            for provider_acc in term_acc.provider_accounts:
                return provider_acc

        raise APIError(
            APIError.INTERNAL,
            f"Provider {provider} account for {channel_id} not found"
        )

    @staticmethod
    def get_provider_accounts(
            recipient: Creator | PayoutChannel,
            cur: cursor
    ) -> List[ProviderAccountType]:
        query = (
            f"SELECT {DEFAULT_COLUMN_LIST} "
            f"FROM public.payout_channel AS pc "
            f"INNER JOIN public.provider_account AS pa "
            f"ON pc.channel_id = pa.channel_id "
        )

        if isinstance(recipient, Creator):
            query += "WHERE pc.creator_id = %s AND pc.removed = False;"
            params = (recipient.creator_id,)
            verification_states = CreatorVerificator.get_verification_states(recipient, cur)
        elif isinstance(recipient, PayoutChannel):
            query += "WHERE pc.channel_id = %s AND pc.removed = False;"
            params = (recipient.channel_id,)
            verification_states = VerificationStates({})
        else:
            logger.warning(f"Unexpected value fro recipient in get_provider_accounts: {recipient}")
            raise APIError(
                APIError.INTERNAL,
                "Unexpected error. Please, contact customer support"
            )

        tmp = AccountFactory._load_accounts(
            query=query,
            parameters=params,
            verification_states=verification_states,
            cur=cur
        )

        result = []
        for _, term_acc in tmp.items():
            for provider_acc in term_acc.provider_accounts:
                result.append(provider_acc)

        return result

    @staticmethod
    def get_proxy_provider_accounts(
            creator: Creator,
            cur: cursor
    ) -> List[ProviderAccountType]:
        if not creator.country:
            return []

        query = (
            f"SELECT {DEFAULT_COLUMN_LIST} "
            f"FROM public.proxy_account AS px "
            f"INNER JOIN public.payout_channel AS pc "
            f"ON px.payout_channel_id = pc.channel_id "
            f"INNER JOIN public.provider_account AS pa "
            f"ON px.payout_channel_id = pa.channel_id "
            f"WHERE px.country = %s AND pc.removed = False;"
        )

        tmp = AccountFactory._load_accounts(
            query=query,
            parameters=(creator.country.name,),
            verification_states=CreatorVerificator.get_verification_states(creator, cur),
            cur=cur
        )

        result = []
        for _, term_acc in tmp.items():
            for provider_acc in term_acc.provider_accounts:
                result.append(provider_acc)

        return result

    @staticmethod
    def get_creator_owned_accounts(
            creator: Creator,
            cur: cursor
    ) -> Dict[uuid.UUID, TerminationAccount]:
        return AccountFactory._load_accounts(
            query=f"SELECT {DEFAULT_COLUMN_LIST} "
                  "FROM public.payout_channel AS pc "
                  "INNER JOIN public.provider_account AS pa "
                  "ON pc.channel_id = pa.channel_id "
                  "WHERE pc.creator_id = %s AND pc.removed = False;",
            parameters=(creator.creator_id,),
            verification_states=CreatorVerificator.get_verification_states(creator, cur),
            cur=cur
        )

    @staticmethod
    def get_proxy_accounts(
            creator: Creator,
            cur: cursor
    ) -> Dict[uuid.UUID, TerminationAccount]:
        if not creator.country:
            raise APIError(
                APIError.INTERNAL,
                "Country is not set"
            )

        return AccountFactory._load_accounts(
            query=f"SELECT {DEFAULT_COLUMN_LIST} "
                  f"FROM public.proxy_account AS px "
                  f"INNER JOIN public.payout_channel AS pc "
                  f"ON px.payout_channel_id = pc.channel_id "
                  f"INNER JOIN public.provider_account AS pa "
                  f"ON px.payout_channel_id = pa.channel_id "
                  f"WHERE px.country = %s AND pc.removed = False;",
            parameters=(creator.country.name,),
            verification_states=CreatorVerificator.get_verification_states(creator, cur),
            cur=cur
        )

    @staticmethod
    def get_crypto_payout_channel(
            channel_id: uuid.UUID,
            cur: cursor,
            with_removed: bool = False,
    ) -> CryptoPayoutChannel:
        cur.execute(
            f"SELECT {PAYOUT_CHANNEL_COLUMNS} "
            f"FROM public.payout_channel AS pc "
            f"WHERE pc.channel_id = %s AND pc.type = 'crypto'"
            f"{' AND removed = False;' if not with_removed else ';'}",
            (channel_id,),
        )

        entry = cur.fetchone()
        if entry is None:
            raise APIError(APIError.OBJECT_NOT_FOUND, f"Crypto account {channel_id} not found")

        return construct_crypto_channel(entry)

    @staticmethod
    def get_circle_account(
            external_id: str,
            cur: cursor,
    ) -> CircleCryptoWallet:
        cur.execute(
            f"SELECT {DEFAULT_COLUMN_LIST} "
            "FROM public.payout_channel AS pc "
            "INNER JOIN public.provider_account AS pa "
            "ON pc.channel_id = pa.channel_id "
            "WHERE pa.provider = %s AND pa.external_id = %s;",
            (PROVIDER_CIRCLE.name, external_id,),
        )

        entry = cur.fetchone()
        if entry is None:
            raise APIError(APIError.INTERNAL, f"Circle wallet {external_id} not found")

        return CircleCryptoWallet.load(
            construct_crypto_channel(entry),
            entry[8],
        )

    @staticmethod
    def get_creator_stripe_bank_accounts(creator: Creator, cur: cursor) -> List[StripeBankAccount]:
        cur.execute(
            f"SELECT {DEFAULT_COLUMN_LIST} "
            "FROM public.payout_channel AS pc "
            "INNER JOIN public.provider_account AS pa "
            "ON pc.channel_id = pa.channel_id "
            "WHERE pc.creator_id = %s "
            "AND pa.provider = 'Stripe' "
            "AND pc.type = 'bank_account'"
            "AND pc.removed = False;",
            (creator.creator_id,)
        )

        result = []
        for entry in cur:
            result.append(
                StripeBankAccount.load(
                    payout_channel=construct_bank_channel(entry),
                    verification_states=CreatorVerificator.get_verification_states(creator, cur),
                    provider_data=StripeBankAccountProviderData.model_validate_json(entry[7]) if entry[7] else None,
                    external_id=entry[8],
                )
            )

        return result

    @staticmethod
    def get_stripe_bank_account(account_id: str, cur: cursor) -> StripeBankAccount:
        cur.execute(
            f"SELECT {DEFAULT_COLUMN_LIST} "
            "FROM public.payout_channel AS pc "
            "INNER JOIN public.provider_account AS pa "
            "ON pc.channel_id = pa.channel_id "
            "WHERE pa.external_id = %s "
            "AND pa.provider = 'Stripe' "
            "AND pc.type = 'bank_account' "
            "AND pc.removed = False;",
            (account_id,)
        )

        entry = cur.fetchone()
        if not entry:
            raise APIError(
                APIError.OBJECT_NOT_FOUND,
                f"Stripe bank account {account_id} not found"
            )

        return StripeBankAccount.load(
            payout_channel=construct_bank_channel(entry),
            verification_states=VerificationStates({}),
            provider_data=StripeBankAccountProviderData.model_validate_json(entry[7]) if entry[7] else None,
            external_id=entry[8],
        )

    @staticmethod
    def get_account_data_from_stripe_account(
            creator: Creator, stripe_bank_account_id: str | None, cur: cursor
    ) -> Tuple[BankAccountData, stripe.BankAccount]:
        if stripe_bank_account_id is None:
            raise APIError(
                APIError.ACCOUNT,
                f"stripe_bank_account_id is not set"
            )

        existing_accounts = AccountFactory.get_creator_stripe_bank_accounts(creator, cur)
        for existing_acc in existing_accounts:
            if existing_acc.external_id == stripe_bank_account_id:
                raise APIError(
                    APIError.ACCOUNT,
                    "Stripe Bank account already attached"
                )

        stripe_account = StripeAccount.get_account_by_creator_id(creator.creator_id, cur)
        if stripe_account is None:
            raise APIError(
                APIError.ACCOUNT,
                f"Unable to create Stripe Proxy account because Stripe account is not set"
            )

        stripe_bank_account = stripe.Account.retrieve_external_account(
            stripe_account.account_id, stripe_bank_account_id, api_key=Config.LIVE_STRIPE_KEY,
        )

        if isinstance(stripe_bank_account, stripe.Card):
            logger.error(f"Stripe external account {stripe_bank_account_id} is Card account")
            raise APIError(APIError.INTERNAL, "Unexpected error. Please, contact customer support")

        country = get_country_by_code(stripe_bank_account.country)
        if not country:
            logger.error(f"Failed to get country name by code {stripe_bank_account.country}")
            raise APIError(APIError.INTERNAL, "Unexpected error. Please, contact customer support")

        return BankAccountData(
            country=country,
            account_holder_type="company",
            account_holder_name="TransferMole",
            currency=stripe_bank_account.currency.upper(),
            bank_name=stripe_bank_account.bank_name,
            account_number=stripe_bank_account.last4,
        ), stripe_bank_account

    @staticmethod
    def attach_circle_crypto_account(
            creator: Creator,
            account_data: CryptoAccountDetails,
            external_id: str,
            cur: cursor,
    ) -> CryptoPayoutChannel:
        if not creator.country:
            raise APIError(
                APIError.INTERNAL,
                f"Country not set for user"
            )

        crypto_payout_channel = CryptoPayoutChannel.create_new(
            creator=creator,
            data=account_data,
            cur=cur
        )

        CircleCryptoWallet.create_new(
            payout_channel=crypto_payout_channel,
            external_id=external_id,
            cur=cur
        )

        if PROVIDER_MERCURYO.name in creator.country.payout_providers:
            if crypto_payout_channel.data.network in MERCURYO_NETWORK_NAME:
                MercuryoCryptoProviderAccount.create_new(
                    payout_channel=crypto_payout_channel,
                    verification_states=CreatorVerificator.get_verification_states(creator, cur),
                    cur=cur,
                )

        return crypto_payout_channel

    @staticmethod
    def attach_self_custody_wallet(
            creator: Creator,
            account_data: CryptoAccountDetails,
            cur: cursor,
    ) -> CryptoPayoutChannel:
        if not creator.country:
            raise APIError(
                APIError.INTERNAL,
                f"Country not set for user"
            )

        crypto_payout_channel = CryptoPayoutChannel.create_new(
            creator=creator,
            data=account_data,
            cur=cur
        )

        for provider in creator.country.payout_providers:
            match provider:
                case PROVIDER_POLYGON.name | PROVIDER_ETHEREUM.name | PROVIDER_AVALANCHE.name | PROVIDER_BASE.name | PROVIDER_BSC.name:
                    SelfCustodyCryptoWallet.create_new(
                        payout_channel=crypto_payout_channel,
                        cur=cur,
                    )

                case PROVIDER_MERCURYO.name:
                    if crypto_payout_channel.data.network in MERCURYO_NETWORK_NAME:
                        MercuryoCryptoProviderAccount.create_new(
                            payout_channel=crypto_payout_channel,
                            verification_states=CreatorVerificator.get_verification_states(creator, cur),
                            cur=cur,
                        )

        send_notification(
            creator.creator_id,
            AccountCreated(
                channel_id=crypto_payout_channel.channel_id,
                type=crypto_payout_channel.channel_type,
            ),
            None,
        )

        return crypto_payout_channel

    @staticmethod
    def attach_bank_account(
            creator: Creator,
            account_data: BankAccountData,
            cur: cursor,
    ) -> BankPayoutChannel:
        if not creator.country:
            raise APIError(
                APIError.INTERNAL,
                f"Country not set for user"
            )

        bank_payout_channel = BankPayoutChannel.create_new(
            creator=creator,
            data=account_data,
            cur=cur
        )

        for provider in creator.country.payout_providers:
            match provider:
                case PROVIDER_STRIPE.name:
                    StripeBankAccount.create_new(
                        creator=creator,
                        payout_channel=bank_payout_channel,
                        verification_states=CreatorVerificator.get_verification_states(creator, cur),
                        stripe_bank_account=None,
                        cur=cur,
                    )

                case PROVIDER_WINDAPP.name:
                    WindappBankAccount.create_new(
                        payout_channel=bank_payout_channel,
                        verification_states=CreatorVerificator.get_verification_states(creator, cur),
                        cur=cur,
                    )

        send_notification(
            creator.creator_id,
            AccountCreated(
                channel_id=bank_payout_channel.channel_id,
                type=bank_payout_channel.channel_type,
            ),
            None,
        )

        return bank_payout_channel

    @staticmethod
    def attach_stripe_bank_account(
            creator: Creator,
            stripe_bank_account_id: str,
            cur: cursor,
    ) -> BankPayoutChannel:
        if not creator.country:
            raise APIError(APIError.CREATOR_COUNTRY_NOT_SELECTED, "Country not set")

        if PROVIDER_STRIPE.name not in creator.country.payout_providers:
            raise APIError(
                APIError.INTERNAL,
                "Stripe is not supported in your country"
            )

        data, stripe_bank_account = AccountFactory.get_account_data_from_stripe_account(
            creator=creator,
            stripe_bank_account_id=stripe_bank_account_id,
            cur=cur
        )

        bank_payout_channel = BankPayoutChannel.create_new(
            creator=creator,
            data=data,
            cur=cur
        )

        StripeBankAccount.create_new(
            creator=creator,
            payout_channel=bank_payout_channel,
            verification_states=CreatorVerificator.get_verification_states(creator, cur),
            stripe_bank_account=stripe_bank_account,
            cur=cur,
        )

        return bank_payout_channel

    @staticmethod
    def get_available_payout_channels(country: Country) -> AvailablePayoutChannels:
        result = AvailablePayoutChannels()
        for provider_name in country.payout_providers:
            match provider_name:
                case PROVIDER_STRIPE.name:
                    result.bank_account = True
                    result.stripe_bank_account = True

                case PROVIDER_WINDAPP.name:
                    result.bank_account = True

                case PROVIDER_POLYGON.name | PROVIDER_ETHEREUM.name | PROVIDER_AVALANCHE.name | PROVIDER_BASE.name | PROVIDER_BSC.name:
                    result.crypto = True

        return result
