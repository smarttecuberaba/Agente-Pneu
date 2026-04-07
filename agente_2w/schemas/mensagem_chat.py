from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Optional, Any

from agente_2w.enums.enums import Direcao, Remetente


class MensagemChatBase(BaseModel):
    sessao_chat_id: UUID
    direcao: Direcao
    remetente: Remetente
    conteudo_texto: str
    criado_em: datetime
    message_id_externo: Optional[str] = None
    metadata_json: Optional[dict[str, Any]] = None


class MensagemChatCreate(MensagemChatBase):
    pass


class MensagemChat(MensagemChatBase):
    id: UUID
    registrado_em: datetime

    model_config = {"from_attributes": True}
