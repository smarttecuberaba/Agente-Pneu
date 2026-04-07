"""Guardrails aplicados ao envelope antes do processamento backend.

Um guardrail ajusta o envelope retornado pela IA quando ele contem combinacoes
contraditorias ou transicoes invalidas. A logica e conservadora: preserva a
acao mais forte (ex.: confirmar_item) e descarta a conflitante.
"""
import logging

from agente_2w.enums.enums import EtapaFluxo

logger = logging.getLogger(__name__)


def _aplicar_guardrail(envelope, etapa_atual):
    """Guardrail: corrige acoes conflitantes no envelope antes do processamento.

    Regras:
    1. confirmar_item + adicionar_outro_item = contradicao → manter confirmar_item
    2. converter_em_pedido + cancelar_pedido = contradicao → manter cancelar_pedido
    3. finalizar_itens + adicionar_outro_item = contradicao → manter finalizar_itens
    4. rejeitar_item + confirmar_item = contradicao → manter rejeitar_item
    """
    acoes = list(envelope.acoes_sugeridas)
    etapa = envelope.etapa_atual

    # Regra 1: confirmar vs adicionar
    if "confirmar_item" in acoes and "adicionar_outro_item" in acoes:
        acoes.remove("adicionar_outro_item")
        logger.info("Guardrail: adicionar_outro_item removido — conflito com confirmar_item")
        if etapa == EtapaFluxo.busca:
            etapa = etapa_atual
            logger.info(
                "Guardrail: etapa_atual revertida de busca para %s", etapa_atual.value
            )

    # Regra 2: converter vs cancelar
    if "converter_em_pedido" in acoes and "cancelar_pedido" in acoes:
        acoes.remove("converter_em_pedido")
        logger.info("Guardrail: converter_em_pedido removido — conflito com cancelar_pedido")

    # Regra 3: finalizar vs adicionar
    if "finalizar_itens" in acoes and "adicionar_outro_item" in acoes:
        acoes.remove("adicionar_outro_item")
        logger.info("Guardrail: adicionar_outro_item removido — conflito com finalizar_itens")
        if etapa == EtapaFluxo.busca:
            etapa = etapa_atual

    # Nota: rejeitar_item + confirmar_item no mesmo turno NAO e contradicao —
    # o cliente pode rejeitar um item e confirmar outro (itens diferentes).
    # Nao remover nenhum dos dois.

    envelope.acoes_sugeridas = acoes
    envelope.etapa_atual = etapa
    return envelope
