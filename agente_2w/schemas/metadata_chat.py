from pydantic import BaseModel
from typing import Optional, Any


class MetadataChat(BaseModel):
    provider: str
    message_id_externo: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
