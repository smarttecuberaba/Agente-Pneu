from pydantic import BaseModel, model_validator, field_validator
from datetime import datetime
from uuid import UUID
from typing import Optional
from decimal import Decimal

from agente_2w.enums.enums import Posicao


class ItemPedidoBase(BaseModel):
    pedido_id: UUID
    pneu_id: UUID
    quantidade: int
    preco_unitario: Decimal
    subtotal: Decimal
    item_provisorio_id: Optional[UUID] = None
    posicao: Optional[Posicao] = None

    @field_validator("quantidade")
    @classmethod
    def quantidade_minima(cls, v):
        if v < 1:
            raise ValueError("quantidade deve ser >= 1")
        return v

    @model_validator(mode="after")
    def subtotal_coerente(self):
        esperado = self.quantidade * self.preco_unitario
        if self.subtotal != esperado:
            raise ValueError(
                f"subtotal ({self.subtotal}) deve ser quantidade * preco_unitario ({esperado})"
            )
        return self


class ItemPedidoCreate(ItemPedidoBase):
    pass


class ItemPedido(ItemPedidoBase):
    id: UUID
    criado_em: datetime

    model_config = {"from_attributes": True}
