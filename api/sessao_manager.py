"""Gerencia sessoes de chat por numero de telefone.

Regra: cada numero tem no maximo uma sessao ativa por vez.
Se a sessao estiver fechada/bloqueada, cria uma nova.
"""

import logging
from uuid import UUID

from agente_2w.db import sessao_repo
from agente_2w.enums.enums import EtapaFluxo, StatusSessao
from agente_2w.schemas.sessao_chat import SessaoChatCreate

logger = logging.getLogger(__name__)

_STATUS_REAPROVEITAVEL = {StatusSessao.ativa, StatusSessao.aguardando_cliente}


def obter_ou_criar_sessao(contato: str) -> UUID:
    """Retorna sessao ativa existente ou cria nova para o contato.

    contato: numero de telefone com DDI, ex: '5521999999999'
    """
    sessao_existente = sessao_repo.buscar_sessao_ativa_por_contato(contato)

    if sessao_existente and sessao_existente.status_sessao in _STATUS_REAPROVEITAVEL:
        logger.debug("Sessao existente reaproveitada: %s", sessao_existente.id)
        return sessao_existente.id

    nova = sessao_repo.criar_sessao(SessaoChatCreate(
        canal="whatsapp",
        contato_externo=contato,
        etapa_atual=EtapaFluxo.identificacao,
        status_sessao=StatusSessao.ativa,
    ))
    logger.info("Nova sessao criada para %s: %s", contato, nova.id)
    return nova.id
