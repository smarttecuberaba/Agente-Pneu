"""Schema Pydantic para fotos de pneus (tabela foto_pneu)."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class FotoPneuBase(BaseModel):
    pneu_id: UUID
    url: str
    tipo: str = "principal"
    ordem: int = 1
    descricao: Optional[str] = None
    ativo: bool = True


class FotoPneu(FotoPneuBase):
    id: UUID
    criado_em: datetime

    model_config = {"from_attributes": True}
