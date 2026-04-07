"""Repositorio de areas de entrega e fretes."""

import logging
import unicodedata
from decimal import Decimal

from agente_2w.db.client import supabase

logger = logging.getLogger(__name__)

_TABELA = "area_entrega"


def _normalizar(texto: str) -> str:
    """Remove acentos e converte para minusculo para comparacao."""
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = sem_acento.encode("ascii", "ignore").decode("ascii")
    return sem_acento.strip().lower()


def consultar_frete(municipio: str, bairro: str | None = None) -> Decimal | None:
    """Retorna o valor do frete para o municipio/bairro informado.

    Prioridade:
    1. municipio + bairro exato
    2. municipio com bairro=NULL (cobre todo o municipio)

    Retorna None se a area nao for coberta.
    """
    if not municipio:
        return None

    try:
        resultado = (
            supabase.table(_TABELA)
            .select("municipio, bairro, valor_frete")
            .eq("ativo", True)
            .execute()
        )
        if not resultado.data:
            return None

        municipio_norm = _normalizar(municipio)
        bairro_norm = _normalizar(bairro) if bairro else None

        # Filtra registros do municipio
        candidatos = [
            r for r in resultado.data
            if _normalizar(r["municipio"]) == municipio_norm
        ]

        if not candidatos:
            logger.info("Municipio '%s' nao coberto para entrega", municipio)
            return None

        # Prioridade 1: bairro especifico
        if bairro_norm:
            for r in candidatos:
                if r["bairro"] and _normalizar(r["bairro"]) == bairro_norm:
                    logger.info(
                        "Frete encontrado: %s / %s = R$%.2f",
                        municipio, bairro, float(r["valor_frete"]),
                    )
                    return Decimal(str(r["valor_frete"]))

        # Prioridade 2: preco municipal (bairro=NULL)
        for r in candidatos:
            if r["bairro"] is None:
                logger.info(
                    "Frete encontrado: %s = R$%.2f", municipio, float(r["valor_frete"])
                )
                return Decimal(str(r["valor_frete"]))

        return None

    except Exception:
        logger.exception("Erro ao consultar frete para '%s'", municipio)
        return None


def listar_municipios_ativos() -> list[str]:
    """Retorna lista de municipios cobertos (para referencia no prompt)."""
    try:
        resultado = (
            supabase.table(_TABELA)
            .select("municipio")
            .eq("ativo", True)
            .is_("bairro", "null")
            .order("municipio")
            .execute()
        )
        return [r["municipio"] for r in resultado.data]
    except Exception:
        logger.exception("Erro ao listar municipios")
        return []


def buscar_tabela_fretes() -> list[dict]:
    """Retorna tabela de fretes por municipio (apenas linhas sem bairro especifico).

    Formato: [{"municipio": "Niteroi", "valor_frete": "9.90"}, ...]
    Usado para expor a tabela completa no contexto da IA, permitindo
    que ela responda perguntas sobre frete proativamente sem nova consulta.
    """
    try:
        resultado = (
            supabase.table(_TABELA)
            .select("municipio, valor_frete")
            .eq("ativo", True)
            .is_("bairro", "null")
            .order("municipio")
            .execute()
        )
        return [
            {"municipio": r["municipio"], "valor_frete": str(Decimal(str(r["valor_frete"])))}
            for r in resultado.data
        ]
    except Exception:
        logger.exception("Erro ao buscar tabela de fretes")
        return []
