import logging
from uuid import UUID

from agente_2w.db.client import supabase
from agente_2w.db.exceptions import RegistroNaoEncontrado, ErroDeInsercao, ErroDeAtualizacao
from agente_2w.schemas.contexto_conversa import ContextoConversa, ContextoConversaCreate

logger = logging.getLogger(__name__)

_TABELA = "contexto_conversa"


def criar_fato(dados: ContextoConversaCreate) -> ContextoConversa:
    try:
        resultado = (
            supabase.table(_TABELA)
            .insert(dados.model_dump(mode="json"))
            .execute()
        )
        logger.debug("Fato criado: chave=%s", dados.chave)
        return ContextoConversa(**resultado.data[0])
    except Exception as e:
        raise ErroDeInsercao(_TABELA, f"chave={dados.chave}: {e}") from e


def desativar_fato_anterior(
    sessao_id: UUID,
    chave: str,
    item_provisorio_id: UUID | None = None,
) -> None:
    try:
        query = (
            supabase.table(_TABELA)
            .update({"ativo": False})
            .eq("sessao_chat_id", str(sessao_id))
            .eq("chave", chave)
            .eq("ativo", True)
        )
        if item_provisorio_id is not None:
            query = query.eq("item_provisorio_id", str(item_provisorio_id))
        else:
            query = query.is_("item_provisorio_id", "null")
        query.execute()
    except Exception as e:
        raise ErroDeAtualizacao(_TABELA, f"desativar chave={chave}: {e}") from e


def registrar_fato(dados: ContextoConversaCreate) -> ContextoConversa:
    desativar_fato_anterior(
        sessao_id=dados.sessao_chat_id,
        chave=dados.chave,
        item_provisorio_id=dados.item_provisorio_id,
    )
    return criar_fato(dados)


def listar_fatos_ativos(sessao_id: UUID) -> list[ContextoConversa]:
    try:
        resultado = (
            supabase.table(_TABELA)
            .select("*")
            .eq("sessao_chat_id", str(sessao_id))
            .eq("ativo", True)
            .order("coletado_em", desc=False)
            .execute()
        )
        return [ContextoConversa(**row) for row in resultado.data]
    except Exception as e:
        raise RegistroNaoEncontrado(_TABELA, str(sessao_id)) from e


def listar_fatos_por_chave(
    sessao_id: UUID,
    chave: str,
) -> list[ContextoConversa]:
    try:
        resultado = (
            supabase.table(_TABELA)
            .select("*")
            .eq("sessao_chat_id", str(sessao_id))
            .eq("chave", chave)
            .order("coletado_em", desc=False)
            .execute()
        )
        return [ContextoConversa(**row) for row in resultado.data]
    except Exception as e:
        raise RegistroNaoEncontrado(_TABELA, f"chave={chave}, sessao={sessao_id}") from e


def buscar_fato_ativo(
    sessao_id: UUID,
    chave: str,
    item_provisorio_id: UUID | None = None,
) -> ContextoConversa | None:
    try:
        query = (
            supabase.table(_TABELA)
            .select("*")
            .eq("sessao_chat_id", str(sessao_id))
            .eq("chave", chave)
            .eq("ativo", True)
        )
        if item_provisorio_id is not None:
            query = query.eq("item_provisorio_id", str(item_provisorio_id))
        else:
            query = query.is_("item_provisorio_id", "null")

        resultado = query.maybe_single().execute()
        if resultado is None or resultado.data is None:
            return None
        return ContextoConversa(**resultado.data)
    except Exception as e:
        raise RegistroNaoEncontrado(_TABELA, f"chave={chave}, sessao={sessao_id}") from e
