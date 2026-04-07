"""
Package orquestrador — loop completo de um turno do agente.

API publica (contrato externo preservado):
    from agente_2w.engine.orquestrador import processar_turno, MENSAGEM_FALHA_SEGURA

Durante a decomposicao, o _nucleo.py contem a implementacao e os submodulos
(guardrails, fatos_fallback, confirmacao_pedido, localidade_frete,
enriquecimento_itens) sao extraidos gradualmente. O __init__.py re-exporta
todos os simbolos usados externamente (incluindo funcoes privadas referenciadas
em testes) para manter compatibilidade com quem ja importa daqui.
"""
from agente_2w.engine.orquestrador._nucleo import (
    # API publica
    processar_turno,
    MENSAGEM_FALHA_SEGURA,
    # Funcoes referenciadas por testes (privadas por convencao, expostas por contrato)
    _aplicar_guardrail,
    _resolver_timeout,
)
from agente_2w.schemas.resposta_turno import RespostaTurno  # noqa: F401 — re-export
from agente_2w.engine.orquestrador.localidade_frete import (
    _atualizar_localidade_cliente,
    _parsear_localidade_endereco,
)
from agente_2w.engine.orquestrador.fatos_fallback import (
    _tem_negacao_antes,
    _KEYWORDS_FORMA_PAGAMENTO,
    _KEYWORDS_TIPO_ENTREGA,
)

__all__ = [
    "processar_turno",
    "RespostaTurno",
    "MENSAGEM_FALHA_SEGURA",
    "_aplicar_guardrail",
    "_resolver_timeout",
    "_atualizar_localidade_cliente",
    "_tem_negacao_antes",
    "_parsear_localidade_endereco",
    "_KEYWORDS_FORMA_PAGAMENTO",
    "_KEYWORDS_TIPO_ENTREGA",
]
