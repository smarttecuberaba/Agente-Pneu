from pydantic import BaseModel, model_validator, field_validator
from datetime import datetime
from uuid import UUID
from typing import Optional, Any
from decimal import Decimal

from agente_2w.enums.enums import TipoEntrega, FormaPagamento, StatusPedido


class PedidoBase(BaseModel):
    sessao_chat_id: UUID
    cliente_id: UUID
    tipo_entrega: TipoEntrega
    forma_pagamento: FormaPagamento
    valor_total: Decimal
    valor_frete: Decimal = Decimal("0")
    status_pedido: StatusPedido
    endereco_entrega_json: Optional[dict[str, Any]] = None

    @field_validator("tipo_entrega")
    @classmethod
    def tipo_entrega_fechado(cls, v):
        if v == TipoEntrega.a_confirmar:
            raise ValueError("pedido nao aceita tipo_entrega = a_confirmar")
        return v

    @field_validator("forma_pagamento")
    @classmethod
    def forma_pagamento_fechada(cls, v):
        if v == FormaPagamento.a_confirmar:
            raise ValueError("pedido nao aceita forma_pagamento = a_confirmar")
        return v

    @model_validator(mode="after")
    def entrega_exige_endereco(self):
        if self.tipo_entrega == TipoEntrega.entrega:
            if not self.endereco_entrega_json:
                raise ValueError(
                    "tipo_entrega = entrega exige endereco_entrega_json"
                )
        return self


class PedidoCreate(PedidoBase):
    pass


class Pedido(PedidoBase):
    id: UUID
    numero_pedido: int
    criado_em: datetime
    atualizado_em: datetime

    model_config = {"from_attributes": True}
