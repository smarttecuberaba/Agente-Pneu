import logging
from uuid import UUID

from agente_2w.db.client import supabase
from agente_2w.db.exceptions import RegistroNaoEncontrado, ErroDeInsercao
from agente_2w.schemas.mensagem_chat import MensagemChat, MensagemChatCreate

logger = logging.getLogger(__name__)

_TABELA = "mensagem_chat"


def criar_mensagem(dados: MensagemChatCreate) -> MensagemChat:
    try:
        resultado = (
            supabase.table(_TABELA)
            .insert(dados.model_dump(mode="json"))
            .execute()
        )
        logger.debug("Mensagem criada: %s", resultado.data[0].get("id"))
        return MensagemChat(**resultado.data[0])
    except Exception as e:
        raise ErroDeInsercao(_TABELA, str(e)) from e


def listar_mensagens_por_sessao(
    sessao_id: UUID,
    limite: int = 20,
) -> list[MensagemChat]:
    try:
        resultado = (
            supabase.table(_TABELA)
            .select("*")
            .eq("sessao_chat_id", str(sessao_id))
            .order("criado_em", desc=False)
            .limit(limite)
            .execute()
        )
        return [MensagemChat(**row) for row in resultado.data]
    except Exception as e:
        raise RegistroNaoEncontrado(_TABELA, str(sessao_id)) from e


def buscar_mensagem_por_id(mensagem_id: UUID) -> MensagemChat | None:
    try:
        resultado = (
            supabase.table(_TABELA)
            .select("*")
            .eq("id", str(mensagem_id))
            .maybe_single()
            .execute()
        )
        if resultado is None or resultado.data is None:
            return None
        return MensagemChat(**resultado.data)
    except Exception as e:
        raise RegistroNaoEncontrado(_TABELA, str(mensagem_id)) from e
