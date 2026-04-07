from pydantic import BaseModel, Field
from typing import Optional, Any

from agente_2w.enums.enums import EtapaFluxo, Confianca


class FatoObservado(BaseModel):
    chave: str
    valor: Any
    mensagem_chat_id: Optional[str] = None


class FatoInferido(BaseModel):
    chave: str
    valor: Any
    justificativa: str


class MudancaContexto(BaseModel):
    chave: str
    valor_novo: Any
    motivo: str


class MudancaItem(BaseModel):
    item_provisorio_id: Optional[str] = None
    acao: str
    dados: Optional[dict[str, Any]] = None


class BloqueioIdentificado(BaseModel):
    codigo_motivo: str
    mensagem_motivo: str
    campo_relacionado: Optional[str] = None


class EnvelopeIA(BaseModel):
    mensagem_cliente: str
    etapa_atual: EtapaFluxo
    intencao_atual: str
    acoes_sugeridas: list[str]
    pendencias: list[str] = Field(default_factory=list)
    confianca: Confianca
    fatos_observados: list[FatoObservado] = Field(default_factory=list)
    fatos_inferidos: list[FatoInferido] = Field(default_factory=list)
    mudancas_contexto: list[MudancaContexto] = Field(default_factory=list)
    mudancas_itens: list[MudancaItem] = Field(default_factory=list)
    bloqueios_identificados: list[BloqueioIdentificado] = Field(default_factory=list)
