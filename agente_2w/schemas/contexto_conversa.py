from pydantic import BaseModel, model_validator
from datetime import datetime
from uuid import UUID
from typing import Optional, Any

from agente_2w.enums.enums import TipoDeVerdade, NivelConfirmacao, OrigemContexto


class ContextoConversaBase(BaseModel):
    sessao_chat_id: UUID
    chave: str
    tipo_de_verdade: TipoDeVerdade
    nivel_confirmacao: NivelConfirmacao
    fonte: OrigemContexto
    valor_texto: Optional[str] = None
    valor_json: Optional[Any] = None
    item_provisorio_id: Optional[UUID] = None
    mensagem_chat_id: Optional[UUID] = None
    referencia_fonte: Optional[str] = None
    observacao: Optional[str] = None
    ativo: bool = True

    @model_validator(mode="after")
    def valor_obrigatorio(self):
        if self.valor_texto is None and self.valor_json is None:
            raise ValueError("valor_texto ou valor_json deve existir")
        return self

    @model_validator(mode="after")
    def mensagem_cliente_exige_mensagem_id(self):
        if self.fonte == OrigemContexto.mensagem_cliente:
            if self.mensagem_chat_id is None:
                raise ValueError(
                    "fonte mensagem_cliente exige mensagem_chat_id"
                )
        return self


class ContextoConversaCreate(ContextoConversaBase):
    pass


class ContextoConversa(ContextoConversaBase):
    id: UUID
    coletado_em: datetime
    criado_em: datetime

    model_config = {"from_attributes": True}
