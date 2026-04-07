from pydantic import BaseModel, model_validator
from datetime import datetime
from uuid import UUID
from typing import Optional


class MotoBase(BaseModel):
    marca: str
    modelo: str
    descricao_resolvida: str
    versao: Optional[str] = None
    ano_inicio: Optional[int] = None
    ano_fim: Optional[int] = None

    @model_validator(mode="after")
    def intervalo_ano_valido(self):
        if self.ano_inicio and self.ano_fim:
            if self.ano_fim < self.ano_inicio:
                raise ValueError("ano_fim deve ser >= ano_inicio")
        return self


class Moto(MotoBase):
    id: UUID
    criado_em: datetime

    model_config = {"from_attributes": True}
