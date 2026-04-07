from pydantic import BaseModel, Field
from datetime import datetime
from decimal import Decimal
from typing import Optional, Any

from agente_2w.enums.enums import (
    EtapaFluxo,
    StatusSessao,
    TipoDeVerdade,
    NivelConfirmacao,
    OrigemContexto,
    StatusItemProvisorio,
)


class SessaoContexto(BaseModel):
    sessao_id: str
    canal: str
    contato_externo: str
    etapa_atual: EtapaFluxo
    status_sessao: StatusSessao
    ultima_interacao_em: datetime


class ItemUltimoPedidoContexto(BaseModel):
    pneu_nome: str
    posicao: Optional[str] = None
    quantidade: int
    preco_unitario: Decimal


class UltimoPedidoContexto(BaseModel):
    data: datetime
    valor_total: Decimal
    forma_pagamento: str
    tipo_entrega: str
    itens: list[ItemUltimoPedidoContexto] = Field(default_factory=list)


class ClienteContexto(BaseModel):
    cliente_id: Optional[str] = None
    nome: Optional[str] = None
    telefone: Optional[str] = None
    resolvido: bool = False
    segmento: Optional[str] = None          # novo | recorrente | vip
    total_pedidos: int = 0
    valor_total_gasto: Optional[Decimal] = None
    ultima_compra_em: Optional[datetime] = None
    municipio: Optional[str] = None
    bairro: Optional[str] = None
    ultimo_pedido: Optional[UltimoPedidoContexto] = None


class BloqueioAtivo(BaseModel):
    codigo_motivo: str
    mensagem_motivo: str
    campo_relacionado: Optional[str] = None
    acao_bloqueada: str


class MensagemRecente(BaseModel):
    mensagem_id: str
    direcao: str
    remetente: str
    conteudo_texto: str
    criado_em: datetime


class FatoAtivo(BaseModel):
    chave: str
    valor: Any
    tipo_de_verdade: TipoDeVerdade
    nivel_confirmacao: NivelConfirmacao
    fonte: OrigemContexto
    mensagem_chat_id: Optional[str] = None
    item_provisorio_id: Optional[str] = None
    coletado_em: datetime


class ResultadoBusca(BaseModel):
    origem: str
    referencia_resultado: str
    pneu_id: Optional[str] = None
    descricao: str
    preco_venda: Optional[Decimal] = None
    quantidade_disponivel: Optional[int] = None
    compatibilidade_status: str
    observacao: Optional[str] = None


class ItemProvisorioContexto(BaseModel):
    item_provisorio_id: str
    pneu_id: Optional[str] = None
    descricao_contextual: str
    posicao: Optional[str] = None
    quantidade: int
    status_item: StatusItemProvisorio
    preco_unitario_sugerido: Optional[Decimal] = None
    cliente_confirmou: bool = False
    validado_backend: bool = False


class Pendencia(BaseModel):
    codigo: str
    descricao: str
    campo_relacionado: Optional[str] = None
    obrigatoria_para: str


class FreteContexto(BaseModel):
    municipio: str
    coberto: bool
    valor_frete: Optional[Decimal] = None
    bairro: Optional[str] = None


class ResumoOperacional(BaseModel):
    tem_item_validado: bool = False
    tem_entrega_definida: bool = False
    tem_pagamento_definido: bool = False
    pode_avancar_etapa: bool = False


class ItemPedidoSessaoContexto(BaseModel):
    pneu_nome: str
    posicao: Optional[str] = None
    quantidade: int
    preco_unitario: Decimal


class PedidoSessaoContexto(BaseModel):
    """Pedido confirmado criado nesta sessão (se já existir)."""
    pedido_id: str
    numero_pedido: int
    status_pedido: str
    valor_total: Decimal
    valor_frete: Decimal
    forma_pagamento: str
    tipo_entrega: str
    endereco_entrega_json: Optional[dict] = None
    itens: list[ItemPedidoSessaoContexto] = Field(default_factory=list)
    criado_em: datetime


class Metadados(BaseModel):
    gerado_em: datetime
    versao_contexto: str = "v1"


class ContextoExecutavel(BaseModel):
    sessao: SessaoContexto
    cliente: ClienteContexto
    bloqueios_ativos: list[BloqueioAtivo] = Field(default_factory=list)
    mensagens_recentes: list[MensagemRecente] = Field(default_factory=list)
    fatos_ativos: list[FatoAtivo] = Field(default_factory=list)
    resultados_busca_atuais: list[ResultadoBusca] = Field(default_factory=list)
    itens_provisorios: list[ItemProvisorioContexto] = Field(default_factory=list)
    pendencias: list[Pendencia] = Field(default_factory=list)
    acoes_permitidas: list[str] = Field(default_factory=list)
    resumo_operacional: ResumoOperacional = Field(default_factory=ResumoOperacional)
    frete: Optional[FreteContexto] = None
    tabela_fretes: list[dict] = Field(default_factory=list)
    config_loja: dict[str, str] = Field(default_factory=dict)
    alertas: list[str] = Field(default_factory=list)
    pedido_sessao_atual: Optional[PedidoSessaoContexto] = None
    metadados: Metadados
