from typing import List, Optional

from pydantic import BaseModel


class ReserveRequest(BaseModel):
    event_id: str
    selected_seats: List[str]


class CreateEventRequest(BaseModel):
    name: str
    venue: str
    start_time: str


class PaymentCaptureRequest(BaseModel):
    intent_id: str
    amount: float


class PaymentConfirmRequest(BaseModel):
    intent_id: str
    razorpay_payment_id: Optional[str] = None
    razorpay_order_id: Optional[str] = None
    razorpay_signature: Optional[str] = None
