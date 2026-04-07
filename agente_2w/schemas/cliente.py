from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from typing import Optional


class ClienteBase(BaseModel):
    telefone: str
    nome: Optional[str] = None
    documento: Optional[str] = None
    municipio: Optional[str] = None
    bairro: Optional[str] = None


class ClienteCreate(ClienteBase):
    pass


class Cliente(ClienteBase):
    id: UUID
    segmento: str = "novo"
    total_pedidos: int = 0
    valor_total_gasto: Decimal = Decimal("0")
    ultima_compra_em: Optional[datetime] = None
    criado_em: datetime
    atualizado_em: datetime

    model_config = {"from_attributes": True}
