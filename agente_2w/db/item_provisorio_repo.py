import logging
from datetime import datetime, timezone
from uuid import UUID

from agente_2w.db.client import supabase
from agente_2w.db.exceptions import RegistroNaoEncontrado, ErroDeInsercao, ErroDeAtualizacao
from agente_2w.schemas.item_provisorio import ItemProvisorio, ItemProvisorioCreate
from agente_2w.enums.enums import StatusItemProvisorio

logger = logging.getLogger(__name__)

_TABELA = "item_provisorio"


def criar_item(dados: ItemProvisorioCreate) -> ItemProvisorio:
    try:
        resultado = (
            supabase.table(_TABELA)
            .insert(dados.model_dump(mode="json"))
            .execute()
        )
        logger.debug("Item provisorio criado: %s", resultado.data[0].get("id"))
        return ItemProvisorio(**resultado.data[0])
    except Exception as e:
        raise ErroDeInsercao(_TABELA, str(e)) from e


def buscar_item_por_id(item_id: UUID) -> ItemProvisorio | None:
    try:
        resultado = (
            supabase.table(_TABELA)
            .select("*")
            .eq("id", str(item_id))
            .maybe_single()
            .execute()
        )
        if resultado is None or resultado.data is None:
            return None
        return ItemProvisorio(**resultado.data)
    except Exception as e:
        raise RegistroNaoEncontrado(_TABELA, str(item_id)) from e


def listar_itens_por_sessao(sessao_id: UUID) -> list[ItemProvisorio]:
    try:
        resultado = (
            supabase.table(_TABELA)
            .select("*")
            .eq("sessao_chat_id", str(sessao_id))
            .order("criado_em", desc=False)
            .execute()
        )
        return [ItemProvisorio(**row) for row in resultado.data]
    except Exception as e:
        raise RegistroNaoEncontrado(_TABELA, str(sessao_id)) from e


def listar_itens_ativos_por_sessao(sessao_id: UUID) -> list[ItemProvisorio]:
    try:
        resultado = (
            supabase.table(_TABELA)
            .select("*")
            .eq("sessao_chat_id", str(sessao_id))
            .in_("status_item", [
                StatusItemProvisorio.sugerido.value,
                StatusItemProvisorio.selecionado_cliente.value,
                StatusItemProvisorio.validado.value,
            ])
            .order("criado_em", desc=False)
            .execute()
        )
        return [ItemProvisorio(**row) for row in resultado.data]
    except Exception as e:
        raise RegistroNaoEncontrado(_TABELA, f"ativos sessao={sessao_id}") from e


def atualizar_status_item(
    item_id: UUID,
    status: StatusItemProvisorio,
) -> ItemProvisorio:
    try:
        payload: dict = {"status_item": status.value}
        if status == StatusItemProvisorio.selecionado_cliente:
            payload["cliente_confirmou_em"] = datetime.now(timezone.utc).isoformat()
        elif status == StatusItemProvisorio.validado:
            payload["validado_backend_em"] = datetime.now(timezone.utc).isoformat()
        resultado = (
            supabase.table(_TABELA)
            .update(payload)
            .eq("id", str(item_id))
            .execute()
        )
        logger.debug("Status item atualizado: %s -> %s", item_id, status.value)
        return ItemProvisorio(**resultado.data[0])
    except Exception as e:
        raise ErroDeAtualizacao(_TABELA, f"status {item_id}: {e}") from e


def vincular_pneu(item_id: UUID, pneu_id: UUID) -> ItemProvisorio:
    try:
        resultado = (
            supabase.table(_TABELA)
            .update({"pneu_id": str(pneu_id)})
            .eq("id", str(item_id))
            .execute()
        )
        logger.debug("Pneu vinculado: item=%s, pneu=%s", item_id, pneu_id)
        return ItemProvisorio(**resultado.data[0])
    except Exception as e:
        raise ErroDeAtualizacao(_TABELA, f"vincular_pneu {item_id}: {e}") from e
