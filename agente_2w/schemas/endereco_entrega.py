from pydantic import BaseModel
from typing import Optional


class EnderecoEntrega(BaseModel):
    logradouro: str
    numero: str
    bairro: str
    cidade: str
    estado: str
    cep: str
    complemento: Optional[str] = None
    referencia: Optional[str] = None
