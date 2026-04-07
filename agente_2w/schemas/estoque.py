from pydantic import BaseModel, field_validator
from datetime import datetime
from uuid import UUID
from typing import Optional
from decimal import Decimal


class EstoqueBase(BaseModel):
    pneu_id: UUID
    quantidade_disponivel: int
    preco_venda: Decimal
    reservado: int = 0
    atualizado_por: Optional[str] = None

    @field_validator("quantidade_disponivel")
    @classmethod
    def quantidade_nao_negativa(cls, v):
        if v < 0:
            raise ValueError("quantidade_disponivel deve ser >= 0")
        return v

    @field_validator("preco_venda")
    @classmethod
    def preco_nao_negativo(cls, v):
        if v < 0:
            raise ValueError("preco_venda deve ser >= 0")
        return v

    @field_validator("reservado")
    @classmethod
    def reservado_nao_negativo(cls, v):
        if v < 0:
            raise ValueError("reservado deve ser >= 0")
        return v


class Estoque(EstoqueBase):
    id: UUID
    atualizado_em: datetime
    criado_em: datetime

    model_config = {"from_attributes": True}
