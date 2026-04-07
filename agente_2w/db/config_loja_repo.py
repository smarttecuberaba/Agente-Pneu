"""Repositorio de configuracoes da loja."""

import logging

from agente_2w.db.client import supabase

logger = logging.getLogger(__name__)

_TABELA = "config_loja"


def buscar_config_loja() -> dict[str, str]:
    """Retorna todas as configuracoes ativas da loja como dicionario chave->valor.

    Usado para expor informacoes operacionais da loja no contexto da IA
    (endereco, horario, politica de montagem, garantia, etc).
    Retorna dict vazio em caso de erro para nao quebrar o fluxo.
    """
    try:
        resultado = (
            supabase.table(_TABELA)
            .select("chave, valor")
            .eq("ativo", True)
            .execute()
        )
        if not resultado.data:
            return {}
        return {r["chave"]: r["valor"] for r in resultado.data}
    except Exception:
        logger.exception("Erro ao buscar config_loja")
        return {}
