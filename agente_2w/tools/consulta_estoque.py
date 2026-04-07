"""Tool de consulta de estoque — chamada pela IA via function calling."""

from uuid import UUID

from agente_2w.db import catalogo_repo


def consultar_estoque(pneu_id: str) -> dict:
    """Consulta disponibilidade e preço de um pneu específico.

    Parâmetros:
        pneu_id: UUID do pneu a consultar

    Retorna dict com disponibilidade, preço e dados do pneu.
    """
    pneu = catalogo_repo.buscar_pneu_por_id(UUID(pneu_id))
    if pneu is None:
        return {"disponivel": False, "mensagem": "Pneu não encontrado no catálogo."}

    estoque = catalogo_repo.buscar_estoque_por_pneu(UUID(pneu_id))
    if estoque is None:
        return {
            "disponivel": False,
            "mensagem": "Sem informação de estoque para este pneu.",
            "pneu": pneu.model_dump(mode="json"),
        }

    disponivel_real = estoque.quantidade_disponivel - estoque.reservado

    return {
        "disponivel": disponivel_real > 0,
        "quantidade_disponivel": estoque.quantidade_disponivel,
        "reservado": estoque.reservado,
        "disponivel_real": disponivel_real,
        "preco_venda": str(estoque.preco_venda),
        "pneu": pneu.model_dump(mode="json"),
    }
