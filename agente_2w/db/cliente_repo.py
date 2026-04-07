import logging
from uuid import UUID

from agente_2w.db.client import supabase
from agente_2w.db.exceptions import RegistroNaoEncontrado, ErroDeInsercao, ErroDeAtualizacao
from agente_2w.schemas.cliente import Cliente, ClienteCreate

logger = logging.getLogger(__name__)

_TABELA = "cliente"


def criar_cliente(dados: ClienteCreate) -> Cliente:
    try:
        resultado = (
            supabase.table(_TABELA)
            .insert(dados.model_dump(mode="json"))
            .execute()
        )
        logger.debug("Cliente criado: %s", resultado.data[0].get("id"))
        return Cliente(**resultado.data[0])
    except Exception as e:
        raise ErroDeInsercao(_TABELA, str(e)) from e


def buscar_cliente_por_id(cliente_id: UUID) -> Cliente | None:
    try:
        resultado = (
            supabase.table(_TABELA)
            .select("*")
            .eq("id", str(cliente_id))
            .maybe_single()
            .execute()
        )
        if resultado is None or resultado.data is None:
            return None
        return Cliente(**resultado.data)
    except Exception as e:
        raise RegistroNaoEncontrado(_TABELA, str(cliente_id)) from e


def buscar_cliente_por_telefone(telefone: str) -> Cliente | None:
    try:
        resultado = (
            supabase.table(_TABELA)
            .select("*")
            .eq("telefone", telefone)
            .maybe_single()
            .execute()
        )
        if resultado is None or resultado.data is None:
            return None
        return Cliente(**resultado.data)
    except Exception as e:
        raise RegistroNaoEncontrado(_TABELA, telefone) from e


def resolver_ou_criar_cliente(telefone: str, nome: str | None = None) -> Cliente:
    existente = buscar_cliente_por_telefone(telefone)
    if existente is not None:
        return existente
    return criar_cliente(ClienteCreate(telefone=telefone, nome=nome))


def atualizar_cliente(cliente_id: UUID, campos: dict) -> Cliente:
    try:
        resultado = (
            supabase.table(_TABELA)
            .update(campos)
            .eq("id", str(cliente_id))
            .execute()
        )
        logger.debug("Cliente atualizado: %s", cliente_id)
        return Cliente(**resultado.data[0])
    except Exception as e:
        raise ErroDeAtualizacao(_TABELA, f"{cliente_id}: {e}") from e
