from typing import List

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
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str
