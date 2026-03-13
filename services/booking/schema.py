from typing import List, Optional

from pydantic import BaseModel


class ReserveRequest(BaseModel):
    event_id: str
    num_seats: int
    preferred_rows: Optional[List[str]] = None
    user_id: Optional[str] = None
