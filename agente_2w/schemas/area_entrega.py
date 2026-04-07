from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Optional
from decimal import Decimal


class AreaEntregaBase(BaseModel):
    municipio: str
    bairro: Optional[str] = None
    valor_frete: Decimal
    ativo: bool = True


class AreaEntrega(AreaEntregaBase):
    id: UUID
    criado_em: datetime

    model_config = {"from_attributes": True}
