"""Extracao fallback de fatos estruturados a partir do texto livre.

Quando a IA esquece de registrar forma_pagamento/tipo_entrega via
fatos_observados, este modulo varre a mensagem do cliente atras de keywords
conhecidas e registra o fato — evitando loops onde a IA repergunta algo que
o cliente ja respondeu.

A funcao _tem_negacao_antes impede falsos positivos (ex.: 'nao quero pix').
"""
import logging
import re
from uuid import UUID

from agente_2w.db import contexto_repo
from agente_2w.constantes import ChaveContexto
from agente_2w.enums.enums import TipoDeVerdade, NivelConfirmacao, OrigemContexto
from agente_2w.schemas.contexto_conversa import ContextoConversaCreate

logger = logging.getLogger(__name__)


_KEYWORDS_FORMA_PAGAMENTO = [
    ("pix", "pix"),
    ("dinheiro", "dinheiro"),
    ("cartão", "cartao"),
    ("cartao", "cartao"),
    ("transferência", "transferencia"),
    ("transferencia", "transferencia"),
]

_KEYWORDS_TIPO_ENTREGA = [
    ("retirada", "retirada"),
    ("retiro", "retirada"),
    ("busco", "retirada"),
    ("entrega", "entrega"),
    ("entregar", "entrega"),
    ("delivery", "entrega"),
]


def _tem_negacao_antes(texto: str, keyword: str) -> bool:
    """Verifica se ha negacao proxima antes da keyword — evita falso positivo.

    Ex: 'nao quero pix' nao deve registrar pix como forma de pagamento.
    """
    pattern = rf"\b(n[aã]o|sem|nunca|n[aã]o\s+quero)\b.{{0,25}}{re.escape(keyword)}"
    return bool(re.search(pattern, texto, re.IGNORECASE))


def _extrair_fatos_estruturados_fallback(
    sessao_id: UUID, mensagem: str, mensagem_id
) -> None:
    """Fallback: registra forma_pagamento e tipo_entrega se a IA nao registrou.

    Roda APOS a IA aplicar fatos_observados. So ativa se o fato ainda nao
    existe na sessao. Previne o loop classico onde o cliente diz 'pix' e a IA
    esquece de registrar, fazendo a mesma pergunta no proximo turno.
    """
    try:
        texto = mensagem.lower()

        # forma_pagamento — so registra se ainda nao existe
        if not contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.FORMA_PAGAMENTO):
            for kw, valor in _KEYWORDS_FORMA_PAGAMENTO:
                if kw in texto and not _tem_negacao_antes(texto, kw):
                    contexto_repo.registrar_fato(ContextoConversaCreate(
                        sessao_chat_id=sessao_id,
                        chave=ChaveContexto.FORMA_PAGAMENTO,
                        valor_texto=valor,
                        valor_json=None,
                        tipo_de_verdade=TipoDeVerdade.observado,
                        nivel_confirmacao=NivelConfirmacao.nenhum,
                        fonte=OrigemContexto.backend,
                        mensagem_chat_id=mensagem_id,
                    ))
                    logger.info(
                        "Fallback: forma_pagamento extraida da mensagem — '%s'", valor
                    )
                    break

        # tipo_entrega — so registra se ainda nao existe
        if not contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.TIPO_ENTREGA):
            for kw, valor in _KEYWORDS_TIPO_ENTREGA:
                if kw in texto and not _tem_negacao_antes(texto, kw):
                    contexto_repo.registrar_fato(ContextoConversaCreate(
                        sessao_chat_id=sessao_id,
                        chave=ChaveContexto.TIPO_ENTREGA,
                        valor_texto=valor,
                        valor_json=None,
                        tipo_de_verdade=TipoDeVerdade.observado,
                        nivel_confirmacao=NivelConfirmacao.nenhum,
                        fonte=OrigemContexto.backend,
                        mensagem_chat_id=mensagem_id,
                    ))
                    logger.info(
                        "Fallback: tipo_entrega extraido da mensagem — '%s'", valor
                    )
                    break

    except Exception:
        logger.exception("Falha no fallback de extracao de fatos estruturados")
