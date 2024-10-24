import uuid
from typing import Optional, Dict, Any

from pydantic import BaseModel


class PaymentData(BaseModel):
    payment_url: Optional[str] = None
    transaction: Optional[Dict[str, Any]] = None
    destination_crypto_address: Optional[str] = None


class PaymentIntent(BaseModel):
    transfer_id: uuid.UUID
    currency: str
    external_id: Optional[str] = None
    payment_data: Optional[PaymentData] = None
