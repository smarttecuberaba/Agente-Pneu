from pydantic import BaseModel, model_validator, field_validator
from datetime import datetime
from uuid import UUID
from typing import Optional
from decimal import Decimal

from agente_2w.enums.enums import StatusItemProvisorio, Posicao


class ItemProvisorioBase(BaseModel):
    sessao_chat_id: UUID
    status_item: StatusItemProvisorio
    pneu_id: Optional[UUID] = None
    posicao: Optional[Posicao] = None
    quantidade: int = 1
    preco_unitario_sugerido: Optional[Decimal] = None
    cliente_confirmou_em: Optional[datetime] = None
    validado_backend_em: Optional[datetime] = None
    observacao: Optional[str] = None

    @field_validator("quantidade")
    @classmethod
    def quantidade_minima(cls, v):
        if v < 1:
            raise ValueError("quantidade deve ser >= 1")
        return v

    @model_validator(mode="after")
    def promovido_exige_pneu(self):
        if self.status_item == StatusItemProvisorio.promovido:
            if self.pneu_id is None:
                raise ValueError("item promovido exige pneu_id")
        return self


class ItemProvisorioCreate(ItemProvisorioBase):
    pass


class ItemProvisorio(ItemProvisorioBase):
    id: UUID
    criado_em: datetime
    atualizado_em: datetime

    model_config = {"from_attributes": True}
