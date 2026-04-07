from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Optional


class CompatibilidadeWebCache(BaseModel):
    id: UUID
    termo_busca: str
    moto_nome: Optional[str] = None
    marca_moto: Optional[str] = None
    ano_moto: Optional[int] = None
    posicao: Optional[str] = None
    largura: Optional[int] = None
    perfil: Optional[int] = None
    aro: Optional[int] = None
    origem: str = "web"
    consultado_em: datetime
    atualizado_em: datetime

    model_config = {"from_attributes": True}
