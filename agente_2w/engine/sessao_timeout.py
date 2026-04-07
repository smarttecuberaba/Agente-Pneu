"""Logica de timeout de sessao.

Regras de negocio:
- Sessao bloqueada por erro tecnico ha mais de TIMEOUT_BLOQUEADA_HORAS → desbloquear
- Sessao inativa ha mais de TIMEOUT_SESSAO_DIAS com contexto valioso → expirada_com_contexto
- Sessao inativa ha mais de TIMEOUT_SESSAO_DIAS sem contexto → expirada_sem_contexto

Etapas com contexto valioso: oferta, confirmacao_item, entrega_pagamento, fechamento.
Cliente estava no meio de uma escolha — vale preservar o historico no cadastro.

Etapas sem contexto relevante: identificacao, busca.
Pouco contexto acumulado — pode recomecar silenciosamente.
"""

from datetime import datetime, timezone, timedelta
from enum import Enum

from agente_2w.schemas.sessao_chat import SessaoChat
from agente_2w.enums.enums import EtapaFluxo, StatusSessao

# --- Configuracao de timeouts ---

# Dias sem interacao para considerar sessao expirada
TIMEOUT_SESSAO_DIAS: int = 7

# Horas para desbloquear sessao travada por erro tecnico
TIMEOUT_BLOQUEADA_HORAS: int = 2

# Etapas com contexto acumulado suficiente para valer registrar a situacao
_ETAPAS_COM_CONTEXTO: frozenset[EtapaFluxo] = frozenset({
    EtapaFluxo.oferta,
    EtapaFluxo.confirmacao_item,
    EtapaFluxo.entrega_pagamento,
    EtapaFluxo.fechamento,
})


class SituacaoSessao(str, Enum):
    ok = "ok"
    # Sessao bloqueada ha mais de TIMEOUT_BLOQUEADA_HORAS — desbloquear
    bloqueada_antiga = "bloqueada_antiga"
    # Inativa ha mais de TIMEOUT_SESSAO_DIAS com etapa com contexto
    expirada_com_contexto = "expirada_com_contexto"
    # Inativa ha mais de TIMEOUT_SESSAO_DIAS em etapa inicial (identificacao/busca)
    expirada_sem_contexto = "expirada_sem_contexto"


def avaliar_sessao(sessao: SessaoChat) -> SituacaoSessao:
    """Avalia se a sessao esta em estado normal ou precisa de tratamento.

    Nao faz nenhuma escrita no banco — apenas classifica.
    Toda a logica de correcao fica no orquestrador (_resolver_timeout).
    """
    # Sessao ja fechada nao deve chegar aqui, mas por seguranca retorna ok
    if sessao.status_sessao == StatusSessao.fechada:
        return SituacaoSessao.ok

    agora = datetime.now(timezone.utc)
    ultima = sessao.ultima_interacao_em

    # Garantir que ultima_interacao_em e timezone-aware
    if ultima.tzinfo is None:
        ultima = ultima.replace(tzinfo=timezone.utc)

    tempo_inativo = agora - ultima

    # Sessao bloqueada: verificar se e bloqueio tecnico antigo
    if sessao.status_sessao == StatusSessao.bloqueada:
        if tempo_inativo > timedelta(hours=TIMEOUT_BLOQUEADA_HORAS):
            return SituacaoSessao.bloqueada_antiga
        # Bloqueio recente — respeitar, nao interferir
        return SituacaoSessao.ok

    # Sessao ativa ou aguardando_cliente: verificar inatividade
    if tempo_inativo > timedelta(days=TIMEOUT_SESSAO_DIAS):
        if sessao.etapa_atual in _ETAPAS_COM_CONTEXTO:
            return SituacaoSessao.expirada_com_contexto
        return SituacaoSessao.expirada_sem_contexto

    return SituacaoSessao.ok
