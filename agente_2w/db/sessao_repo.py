import logging
from uuid import UUID
from datetime import datetime, timezone

from agente_2w.db.client import supabase
from agente_2w.db.exceptions import RegistroNaoEncontrado, ErroDeInsercao, ErroDeAtualizacao
from agente_2w.schemas.sessao_chat import SessaoChat, SessaoChatCreate
from agente_2w.enums.enums import EtapaFluxo, StatusSessao

logger = logging.getLogger(__name__)

_TABELA = "sessao_chat"


def criar_sessao(dados: SessaoChatCreate) -> SessaoChat:
    try:
        resultado = (
            supabase.table(_TABELA)
            .insert(dados.model_dump(mode="json"))
            .execute()
        )
        logger.debug("Sessao criada: %s", resultado.data[0].get("id"))
        return SessaoChat(**resultado.data[0])
    except Exception as e:
        raise ErroDeInsercao(_TABELA, str(e)) from e


def buscar_sessao_por_id(sessao_id: UUID) -> SessaoChat | None:
    try:
        resultado = (
            supabase.table(_TABELA)
            .select("*")
            .eq("id", str(sessao_id))
            .maybe_single()
            .execute()
        )
        if resultado is None or resultado.data is None:
            return None
        return SessaoChat(**resultado.data)
    except Exception as e:
        raise RegistroNaoEncontrado(_TABELA, str(sessao_id)) from e


def buscar_sessao_ativa_por_contato(contato_externo: str) -> SessaoChat | None:
    try:
        resultado = (
            supabase.table(_TABELA)
            .select("*")
            .eq("contato_externo", contato_externo)
            .neq("status_sessao", StatusSessao.fechada.value)
            .order("criado_em", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )
        if resultado is None or resultado.data is None:
            return None
        return SessaoChat(**resultado.data)
    except Exception as e:
        raise RegistroNaoEncontrado(_TABELA, contato_externo) from e


def atualizar_etapa(sessao_id: UUID, etapa: EtapaFluxo) -> SessaoChat:
    try:
        resultado = (
            supabase.table(_TABELA)
            .update({
                "etapa_atual": etapa.value,
                "ultima_interacao_em": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", str(sessao_id))
            .execute()
        )
        logger.debug("Etapa atualizada: %s -> %s", sessao_id, etapa.value)
        return SessaoChat(**resultado.data[0])
    except Exception as e:
        raise ErroDeAtualizacao(_TABELA, f"etapa {sessao_id}: {e}") from e


def atualizar_status(
    sessao_id: UUID,
    status: StatusSessao,
    codigo_motivo: str | None = None,
    mensagem_motivo: str | None = None,
    campo_relacionado: str | None = None,
    acao_bloqueada: str | None = None,
) -> SessaoChat:
    payload: dict = {
        "status_sessao": status.value,
        "ultima_interacao_em": datetime.now(timezone.utc).isoformat(),
    }
    if status == StatusSessao.bloqueada:
        payload["codigo_motivo"] = codigo_motivo
        payload["mensagem_motivo"] = mensagem_motivo
        payload["campo_relacionado"] = campo_relacionado
        payload["acao_bloqueada"] = acao_bloqueada
    else:
        payload["codigo_motivo"] = None
        payload["mensagem_motivo"] = None
        payload["campo_relacionado"] = None
        payload["acao_bloqueada"] = None

    try:
        resultado = (
            supabase.table(_TABELA)
            .update(payload)
            .eq("id", str(sessao_id))
            .execute()
        )
        logger.debug("Status atualizado: %s -> %s", sessao_id, status.value)
        return SessaoChat(**resultado.data[0])
    except Exception as e:
        raise ErroDeAtualizacao(_TABELA, f"status {sessao_id}: {e}") from e


def fechar_sessao(sessao_id: UUID) -> SessaoChat:
    """Fecha a sessao (sem pedido — apenas encerramento administrativo).

    Para fechamento via pedido confirmado, use a RPC promover_para_pedido.
    """
    return atualizar_status(sessao_id, StatusSessao.fechada)


def vincular_cliente(sessao_id: UUID, cliente_id: UUID) -> SessaoChat:
    try:
        resultado = (
            supabase.table(_TABELA)
            .update({
                "cliente_id": str(cliente_id),
                "ultima_interacao_em": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", str(sessao_id))
            .execute()
        )
        logger.debug("Cliente vinculado: sessao=%s, cliente=%s", sessao_id, cliente_id)
        return SessaoChat(**resultado.data[0])
    except Exception as e:
        raise ErroDeAtualizacao(_TABELA, f"vincular_cliente {sessao_id}: {e}") from e
