from pydantic import BaseModel, field_validator
from datetime import datetime
from uuid import UUID

from agente_2w.enums.enums import Posicao


class MedidaMotoBase(BaseModel):
    moto_id: UUID
    posicao: Posicao
    largura: int
    perfil: int
    aro: int
    fonte: str = "curadoria_2w"

    @field_validator("largura")
    @classmethod
    def largura_positiva(cls, v):
        if v <= 0:
            raise ValueError("largura deve ser > 0")
        return v

    @field_validator("perfil")
    @classmethod
    def perfil_positivo(cls, v):
        if v <= 0:
            raise ValueError("perfil deve ser > 0")
        return v

    @field_validator("aro")
    @classmethod
    def aro_positivo(cls, v):
        if v <= 0:
            raise ValueError("aro deve ser > 0")
        return v


class MedidaMotoCreate(MedidaMotoBase):
    pass


class MedidaMoto(MedidaMotoBase):
    id: UUID
    criado_em: datetime

    model_config = {"from_attributes": True}
