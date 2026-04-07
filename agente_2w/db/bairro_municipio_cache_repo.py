"""Repositório de cache bairro→município.

Evita chamadas repetidas ao web_search para o mesmo termo digitado pelo cliente.
A chave do cache é o termo normalizado (lowercase, sem acentos) — assim
"Bangu", "bangu" e "BANGU" viram a mesma entrada.
"""
import logging
import unicodedata
from datetime import datetime, timezone

from agente_2w.db.client import supabase

logger = logging.getLogger(__name__)

_TABELA = "bairro_municipio_cache"


def _normalizar(texto: str) -> str:
    """Lowercase + remove acentos para chave de cache."""
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = sem_acento.encode("ascii", "ignore").decode("ascii")
    return sem_acento.strip().lower()


def buscar(termo: str) -> dict | None:
    """Busca no cache pelo termo normalizado.

    Retorna dict com chaves 'bairro' e 'municipio', ou None se não houver entrada.
    municipio=None no dict significa área fora de cobertura (também cacheado).
    """
    if not termo:
        return None

    chave = _normalizar(termo)
    try:
        res = (
            supabase.table(_TABELA)
            .select("bairro, municipio")
            .eq("termo_normalizado", chave)
            .limit(1)
            .execute()
        )
        if res.data:
            # Incrementa contador de acessos (fire-and-forget)
            try:
                supabase.table(_TABELA).update(
                    {"acessos": res.data[0].get("acessos", 1) + 1,
                     "atualizado_em": datetime.now(timezone.utc).isoformat()}
                ).eq("termo_normalizado", chave).execute()
            except Exception:
                pass  # não quebra o fluxo principal
            return {"bairro": res.data[0]["bairro"], "municipio": res.data[0]["municipio"]}
        return None
    except Exception:
        logger.exception("Erro ao buscar cache para termo '%s'", termo)
        return None


def salvar(
    termo_original: str,
    bairro: str | None,
    municipio: str | None,
    fonte: str = "web_search",
) -> None:
    """Salva (ou atualiza) entrada no cache.

    municipio=None indica área fora de cobertura — também é salvo para
    evitar nova chamada ao web_search para o mesmo termo.
    """
    if not termo_original:
        return

    chave = _normalizar(termo_original)
    try:
        supabase.table(_TABELA).upsert({
            "termo_normalizado": chave,
            "termo_original": termo_original,
            "bairro": bairro,
            "municipio": municipio,
            "fonte": fonte,
            "acessos": 1,
            "atualizado_em": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="termo_normalizado").execute()
        logger.info(
            "Cache salvo: '%s' → bairro=%s, municipio=%s [%s]",
            termo_original, bairro, municipio, fonte,
        )
    except Exception:
        logger.exception("Erro ao salvar cache para termo '%s'", termo_original)
