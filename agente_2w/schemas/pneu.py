from pydantic import BaseModel, field_validator
from datetime import datetime
from uuid import UUID
from typing import Optional


class PneuBase(BaseModel):
    marca: str
    modelo: str
    medida: str
    largura: int
    perfil: int
    aro: int
    descricao_comercial: str
    ativo: bool = True
    sku: Optional[str] = None
    tipo: Optional[str] = None

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


class Pneu(PneuBase):
    id: UUID
    criado_em: datetime
    atualizado_em: datetime

    model_config = {"from_attributes": True}
