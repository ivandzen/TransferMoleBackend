import datetime
import uuid
import requests
import logging
from pydantic import BaseModel, RootModel
from typing import Literal, Annotated, List, Optional
from decimal import Decimal


from .common.config import Config
from .common.api_error import APIError


logger = logging.getLogger(__name__)
session = requests.Session()

UserStatus = Annotated[str, Literal["ENABLED", "DISABLED"]]
UserPinStatus = Annotated[str, Literal["ENABLED", "UNSET", "LOCKED"]]
UserSecurityQuestionStatus = Annotated[str, Literal["ENABLED", "UNSET"]]


class UserPinDetails(BaseModel):
    failedAttempts: int
    lockedData: datetime.datetime
    lockedExpiryDate: datetime.datetime
    lastLockOverrideDate: datetime.datetime

class UserSecurityQuestionDetails(BaseModel):
    failedAttempts: int
    lockedData: datetime.datetime
    lockedExpiryDate: datetime.datetime
    lastLockOverrideDate: datetime.datetime


class CircleUser(BaseModel):
    id: uuid.UUID
    createDate: datetime.datetime
    pinStatus: UserPinStatus
    status: UserStatus
    securityQuestionStatus: UserSecurityQuestionStatus
    pinDetails: UserPinDetails
    securityQuestionDetails: UserSecurityQuestionDetails


class CircleUserData(BaseModel):
    user: CircleUser


class CircleGetUserResponse(BaseModel):
    data: CircleUserData


def circle_get_user(userid: uuid.UUID) -> CircleUser:
    response = session.get(
        url=f"https://api.circle.com/v1/w3s/users/{userid}",
        headers={
            'Authorization': f'Bearer {Config.CIRCLE_API_KEY}',
        },
    )

    if response.status_code == 200 or response.status_code == 201:
        return CircleGetUserResponse.model_validate(response.json()).data.user

    json = response.json()
    logger.info(f"{json}")
    raise APIError(APIError.INTERNAL, f"Circle error: {json.get('message', None)}")


def circle_create_user(userid: uuid.UUID) -> None:
    response = session.post(
        url="https://api.circle.com/v1/w3s/users",
        headers={
            'Authorization': f'Bearer {Config.CIRCLE_API_KEY}',
        },
        json={
            "userId": str(userid),
        }
    )

    if response.status_code == 200 or response.status_code == 201:
        return

    json = response.json()
    logger.info(f"{json}")
    raise APIError(APIError.INTERNAL, f"Circle error: {json.get('message', None)}")


class CircleUserTokenData(BaseModel):
    userToken: str
    encryptionKey: str


class CircleUserTokenResponse(BaseModel):
    data: CircleUserTokenData


class CircleUserStatusData(BaseModel):
    id: uuid.UUID
    createDate: datetime.datetime
    pinStatus: UserPinStatus
    status: UserStatus
    securityQuestionStatus: UserSecurityQuestionStatus


class CircleUserStatus(BaseModel):
    data: CircleUserStatusData


class CircleWalletData(BaseModel):
    id: uuid.UUID
    state: Annotated[str, Literal["LIVE", "FROZEN"]]
    walletSetId: uuid.UUID
    custodyType: Annotated[str, Literal["DEVELOPER", "ENDUSER"]]
    userId: uuid.UUID
    address: str
    blockchain: Annotated[str, Literal["ETH-GOERLI", "ETH-SEPOLIA", "ETH", "MATIC-MUMBAI", "MATIC", "AVAX-FUJI", "AVAX"]]
    accountType: Annotated[str, Literal["EOA", "SCA"]]
    updateDate: datetime.datetime
    createDate: datetime.datetime


class CircleWalletSubdata(BaseModel):
    wallet: CircleWalletData


class CircleWallet(BaseModel):
    data: CircleWalletSubdata


class CircleWalletListData(BaseModel):
    wallets: List[CircleWalletData]


class CircleWalletList(BaseModel):
    data: CircleWalletListData


class CircleToken(BaseModel):
    id: uuid.UUID
    blockchain: str
    tokenAddress: Optional[str] = None
    standard: Optional[str] = None
    name: str
    symbol: str
    decimals: int
    isNative: bool
    updateDate: datetime.datetime
    createDate: datetime.datetime


class CircleTokenBalance(BaseModel):
    token: CircleToken
    amount: Decimal
    amountInUSD: Decimal
    updateDate: datetime.datetime


class TokenBalances(BaseModel):
    tokenBalances: List[CircleTokenBalance]


class TokenBalancesResponse(BaseModel):
    data: TokenBalances


class GasParams(BaseModel):
    gasLimit: int
    baseFee: Decimal
    priorityFee: Decimal
    maxFee: Decimal


class EstimateGasData(BaseModel):
    low: GasParams
    medium: GasParams
    high: GasParams
    callGasLimit: Optional[int] = None
    verificationGasLimit: Optional[int] = None
    preVerificationGas: Optional[int] = None


class EstimateGasResponse(BaseModel):
    data: EstimateGasData


class TokenDetailsData(BaseModel):
    token: CircleToken

class TokenDetailsResponse(BaseModel):
    data: TokenDetailsData


def circle_get_user_token(userid: uuid.UUID) -> CircleUserTokenResponse:
    response = requests.post(
        url="https://api.circle.com/v1/w3s/users/token",
        headers={
            "authorization": f"Bearer {Config.CIRCLE_API_KEY}"
        },
        json={
            "userId": str(userid)
        }
    )

    if response.status_code == 200 or response.status_code == 201:
        return CircleUserTokenResponse.model_validate(response.json())

    json = response.json()
    logger.info(f"{json}")
    raise APIError(APIError.INTERNAL, f"Circle error: {json.get('message', None)}")


def get_circle_network(network: str) -> str:
    match network:
        case "Ethereum":
            return "ETH"
        case "Polygon":
            return "MATIC"
        case "Avalanche C-Chain":
            return "AVAX"
        case "Base":
            return "BASE"
        case unknown:
            raise APIError(APIError.INTERNAL, f"Unknown blockchain {unknown}")


def get_transfermole_network(network: str) -> str:
    match network:
        case "ETH-SEPOLIA" | "ETH":
            return "Ethereum"
        case "MATIC-MUMBAI" | "MATIC":
            return "Polygon"
        case "AVAX-FUJI" | "AVAX":
            return "Avalanche C-Chain"
        case "BASE":
            return "Base"
        case unknown:
            raise APIError(APIError.INTERNAL, f"Unknown blockchain {unknown}")


def circle_user_initialize(user_token: str, network: str) -> str:
    response = requests.post(
        url="https://api.circle.com/v1/w3s/user/initialize",
        headers={
            "authorization": f"Bearer {Config.CIRCLE_API_KEY}",
            "X-User-Token": user_token,
        },
        json={
            "idempotencyKey": str(uuid.uuid4()),
            "blockchains": [get_circle_network(network)],
        }
    )

    if response.status_code == 200 or response.status_code == 201:
        return response.json()['data']['challengeId']

    json = response.json()
    logger.info(f"{json}")
    raise APIError(APIError.INTERNAL, f"Circle error: {json.get('message', None)}")


def circle_get_user_status(user_token: str) -> CircleUserStatus:
    response = requests.get(
        url=f"https://api.circle.com/v1/w3s/user",
        headers={
            "authorization": f"Bearer {Config.CIRCLE_API_KEY}",
            "X-User-Token": user_token,
        },
    )

    if response.status_code == 200 or response.status_code == 201:
        return CircleUserStatus.model_validate(response.json())

    json = response.json()
    logger.info(f"{json}")
    raise APIError(APIError.INTERNAL, f"Circle error: {json.get('message', None)}")


def circle_get_wallets(userid: uuid.UUID) -> CircleWalletList:
    response = requests.get(
        url=f"https://api.circle.com/v1/w3s/wallets?userId={userid}",
        headers={
            "authorization": f"Bearer {Config.CIRCLE_API_KEY}",
        },
    )

    if response.status_code == 200 or response.status_code == 201:
        return CircleWalletList.model_validate(response.json())

    json = response.json()
    logger.info(f"{json}")
    raise APIError(APIError.INTERNAL, f"Circle error: {json.get('message', None)}")


def circle_create_wallet(user_token: str, network: str) -> str:
    response = requests.post(
        url="https://api.circle.com/v1/w3s/user/wallets",
        headers={
            "authorization": f"Bearer {Config.CIRCLE_API_KEY}",
            "X-User-Token": user_token,
        },
        json={
            "idempotencyKey": str(uuid.uuid4()),
            "blockchains": [get_circle_network(network)],
        }
    )

    if response.status_code == 200 or response.status_code == 201:
        return response.json()['data']['challengeId']

    json = response.json()
    logger.info(f"{json}")
    raise APIError(APIError.INTERNAL, f"Circle error: {json.get('message', None)}")


def circle_get_wallet(user_token: str, wallet_id: uuid.UUID) -> CircleWallet:
    response = requests.get(
        url=f"https://api.circle.com/v1/w3s/wallets/{wallet_id}",
        headers={
            "authorization": f"Bearer {Config.CIRCLE_API_KEY}",
            "X-User-Token": user_token,
        },
    )

    if response.status_code == 200 or response.status_code == 201:
        return CircleWallet.model_validate(response.json())

    json = response.json()
    logger.info(f"{json}")
    raise APIError(APIError.INTERNAL, f"Circle error: {json.get('message', None)}")


def circle_get_wallet_balances(
        wallet_id: uuid.UUID, token_address: str | None = None
) -> TokenBalancesResponse:
    response = requests.get(
        url=f"https://api.circle.com/v1/w3s/wallets/{wallet_id}/balances"
            + (f"?tokenAddress={token_address}" if token_address else ""),
        headers={"authorization": f"Bearer {Config.CIRCLE_API_KEY}"}
    )

    if response.status_code == 200 or response.status_code == 201:
        return TokenBalancesResponse.model_validate(response.json())

    json = response.json()
    logger.info(f"{json}")
    raise APIError(APIError.INTERNAL, f"Circle error: {json.get('message', None)}")


def circle_estimate_transfer_fee(
        source: str, destination: str, amount: Decimal, token: CircleToken
) -> EstimateGasResponse:
    response = requests.post(
        url=f"https://api.circle.com/v1/w3s/transactions/transfer/estimateFee",
        headers={"authorization": f"Bearer {Config.CIRCLE_API_KEY}"},
        json={
            "amounts": [str(amount)],
            "destinationAddress": destination,
            "tokenId": str(token.id),
            "sourceAddress": str(source)
        }
    )

    if response.status_code == 200 or response.status_code == 201:
        return EstimateGasResponse.model_validate(response.json())

    json = response.json()
    logger.info(f"{json}")
    raise APIError(APIError.INTERNAL, f"Circle error: {json.get('message', None)}")


def circle_initiate_transfer(
        user_token: str,
        source_wallet_id: uuid.UUID,
        destination: str,
        amount: Decimal,
        token: CircleToken,
        gas_params: GasParams,
        transfer_id: uuid.UUID,
) -> str:
    response = requests.post(
        url=f"https://api.circle.com/v1/w3s/user/transactions/transfer",
        headers={
            "authorization": f"Bearer {Config.CIRCLE_API_KEY}",
            "X-User-Token": user_token,
        },
        json={
            "amounts": [str(amount)],
            "destinationAddress": destination,
            "tokenId": str(token.id),
            "walletId": str(source_wallet_id),
            "gasLimit": str(gas_params.gasLimit),
            "maxFee": str(gas_params.maxFee),
            "priorityFee": str(gas_params.priorityFee),
            "idempotencyKey": str(uuid.uuid4()),
            "refId": str(transfer_id),
        }
    )

    if response.status_code == 200 or response.status_code == 201:
        return response.json()['data']['challengeId']

    json = response.json()
    logger.info(f"{json}")
    raise APIError(APIError.INTERNAL, f"Circle error: {json.get('message', None)}")


def circle_get_token_details(token_id: uuid.UUID) -> TokenDetailsResponse:
    response = requests.get(
        url=f"https://api.circle.com/v1/w3s/tokens/{token_id}",
        headers={
            "authorization": f"Bearer {Config.CIRCLE_API_KEY}",
        },
    )

    if response.status_code == 200 or response.status_code == 201:
        logger.info(response.text)
        return TokenDetailsResponse.model_validate(response.json())

    raise APIError(APIError.INTERNAL, f"Failed to get circle token: {response.text}")


def circle_restore_pin(user_token: str) -> str:
    response = requests.post(
        url=f"https://api.circle.com/v1/w3s/user/pin/restore",
        headers={
            "authorization": f"Bearer {Config.CIRCLE_API_KEY}",
            "X-User-Token": user_token,
        },
        json={"idempotencyKey": str(uuid.uuid4())}
    )

    if response.status_code == 200 or response.status_code == 201:
        return response.json()['data']['challengeId']

    json = response.json()
    logger.info(f"{json}")
    raise APIError(APIError.INTERNAL, f"Circle error: {json.get('message', None)}")