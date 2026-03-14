from typing import List, Optional

from pydantic import BaseModel


class ReserveRequest(BaseModel):
    event_id: str
    num_seats: Optional[int] = None
    preferred_seats: Optional[List[str]] = None


class CreateEventRequest(BaseModel):
    name: str
    venue: str
    start_time: str
