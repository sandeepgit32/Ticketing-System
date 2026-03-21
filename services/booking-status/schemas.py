from typing import List, Optional

from pydantic import BaseModel


class BookingDetails(BaseModel):
    booking_id: str
    event_id: str
    event_name: str
    event_start_time: Optional[str] = None
    user_email: str
    status: str  # reserved, confirmed, expired, cancelled
    seats: List[str]
    payment_status: str
    total_amount: Optional[float] = None
    created_at: str
    updated_at: str
    expires_at: Optional[str] = None


class UserBookingsResponse(BaseModel):
    bookings: List[BookingDetails]
    total: int
