"""Repositório de fotos de pneus (tabela foto_pneu)."""

import logging
from uuid import UUID

from agente_2w.db.client import supabase

logger = logging.getLogger(__name__)

_TABELA = "foto_pneu"


def buscar_foto_principal(pneu_id: UUID) -> str | None:
    """Retorna URL da foto principal do pneu, ou None."""
    try:
        res = (
            supabase.table(_TABELA)
            .select("url")
            .eq("pneu_id", str(pneu_id))
            .eq("tipo", "principal")
            .eq("ativo", True)
            .order("ordem")
            .limit(1)
            .execute()
        )
        return res.data[0]["url"] if res.data else None
    except Exception:
        logger.exception("Erro ao buscar foto principal pneu %s", pneu_id)
        return None


def listar_fotos(pneu_id: UUID) -> list[dict]:
    """Retorna todas as fotos ativas de um pneu, ordenadas."""
    try:
        res = (
            supabase.table(_TABELA)
            .select("url, tipo, ordem, descricao")
            .eq("pneu_id", str(pneu_id))
            .eq("ativo", True)
            .order("ordem")
            .execute()
        )
        return res.data or []
    except Exception:
        logger.exception("Erro ao listar fotos pneu %s", pneu_id)
        return []
