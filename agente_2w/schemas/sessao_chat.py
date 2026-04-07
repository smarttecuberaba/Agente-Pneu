from pydantic import BaseModel, model_validator
from datetime import datetime
from uuid import UUID
from typing import Optional

from agente_2w.enums.enums import EtapaFluxo, StatusSessao


class SessaoChatBase(BaseModel):
    canal: str
    contato_externo: str
    etapa_atual: EtapaFluxo
    status_sessao: StatusSessao
    cliente_id: Optional[UUID] = None
    codigo_motivo: Optional[str] = None
    mensagem_motivo: Optional[str] = None
    campo_relacionado: Optional[str] = None
    acao_bloqueada: Optional[str] = None

    @model_validator(mode="after")
    def bloqueio_exige_motivo(self):
        if self.status_sessao == StatusSessao.bloqueada:
            if not self.codigo_motivo or not self.mensagem_motivo:
                raise ValueError(
                    "sessao bloqueada exige codigo_motivo e mensagem_motivo"
                )
        return self


class SessaoChatCreate(SessaoChatBase):
    pass


class SessaoChat(SessaoChatBase):
    id: UUID
    ultima_interacao_em: datetime
    criado_em: datetime
    atualizado_em: datetime

    model_config = {"from_attributes": True}
