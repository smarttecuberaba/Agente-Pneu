import logging
from uuid import UUID

from agente_2w.db.client import supabase
from agente_2w.db.exceptions import RegistroNaoEncontrado, ErroDeInsercao, ErroDeAtualizacao
from agente_2w.schemas.pedido import Pedido, PedidoCreate
from agente_2w.schemas.item_pedido import ItemPedido, ItemPedidoCreate

logger = logging.getLogger(__name__)


def criar_pedido(dados: PedidoCreate) -> Pedido:
    try:
        resultado = (
            supabase.table("pedido")
            .insert(dados.model_dump(mode="json"))
            .execute()
        )
        logger.debug("Pedido criado: %s", resultado.data[0].get("id"))
        return Pedido(**resultado.data[0])
    except Exception as e:
        raise ErroDeInsercao("pedido", str(e)) from e


def buscar_pedido_por_id(pedido_id: UUID) -> Pedido | None:
    try:
        resultado = (
            supabase.table("pedido")
            .select("*")
            .eq("id", str(pedido_id))
            .maybe_single()
            .execute()
        )
        if resultado is None or resultado.data is None:
            return None
        return Pedido(**resultado.data)
    except Exception as e:
        raise RegistroNaoEncontrado("pedido", str(pedido_id)) from e


def buscar_pedido_por_sessao(sessao_id: UUID) -> Pedido | None:
    try:
        resultado = (
            supabase.table("pedido")
            .select("*")
            .eq("sessao_chat_id", str(sessao_id))
            .maybe_single()
            .execute()
        )
        if resultado is None or resultado.data is None:
            return None
        return Pedido(**resultado.data)
    except Exception as e:
        raise RegistroNaoEncontrado("pedido", f"sessao={sessao_id}") from e


def atualizar_pedido(pedido_id: UUID, campos: dict) -> Pedido:
    """Atualiza campos editaveis do pedido (forma_pagamento, tipo_entrega, endereco_entrega_json)."""
    try:
        resultado = (
            supabase.table("pedido")
            .update(campos)
            .eq("id", str(pedido_id))
            .execute()
        )
        logger.info("Pedido %s atualizado: %s", pedido_id, list(campos.keys()))
        return Pedido(**resultado.data[0])
    except Exception as e:
        raise ErroDeAtualizacao("pedido", f"{pedido_id}: {e}") from e


def cancelar_pedido(pedido_id: UUID) -> Pedido:
    try:
        resultado = (
            supabase.table("pedido")
            .update({"status_pedido": "cancelado"})
            .eq("id", str(pedido_id))
            .execute()
        )
        logger.info("Pedido cancelado: %s", pedido_id)
        return Pedido(**resultado.data[0])
    except Exception as e:
        raise ErroDeAtualizacao("pedido", f"{pedido_id}: {e}") from e


def criar_item_pedido(dados: ItemPedidoCreate) -> ItemPedido:
    try:
        resultado = (
            supabase.table("item_pedido")
            .insert(dados.model_dump(mode="json"))
            .execute()
        )
        logger.debug("Item pedido criado: %s", resultado.data[0].get("id"))
        return ItemPedido(**resultado.data[0])
    except Exception as e:
        raise ErroDeInsercao("item_pedido", str(e)) from e


def buscar_ultimo_pedido_confirmado(cliente_id: UUID, excluir_sessao_id: UUID | None = None) -> Pedido | None:
    """Retorna o pedido confirmado mais recente do cliente, excluindo a sessao atual."""
    try:
        query = (
            supabase.table("pedido")
            .select("*")
            .eq("cliente_id", str(cliente_id))
            .eq("status_pedido", "confirmado")
            .order("criado_em", desc=True)
            .limit(1)
        )
        if excluir_sessao_id:
            query = query.neq("sessao_chat_id", str(excluir_sessao_id))
        resultado = query.execute()
        if not resultado.data:
            return None
        return Pedido(**resultado.data[0])
    except Exception as e:
        logger.debug("buscar_ultimo_pedido_confirmado: %s", e)
        return None


def listar_itens_pedido(pedido_id: UUID) -> list[ItemPedido]:
    try:
        resultado = (
            supabase.table("item_pedido")
            .select("*")
            .eq("pedido_id", str(pedido_id))
            .order("criado_em", desc=False)
            .execute()
        )
        return [ItemPedido(**row) for row in resultado.data]
    except Exception as e:
        raise RegistroNaoEncontrado("item_pedido", f"pedido={pedido_id}") from e
