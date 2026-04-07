"""Repositório de cache compatibilidade moto→medida descoberta via web.

Evita chamadas repetidas ao web_search para a mesma moto/posição.
A chave do cache é (termo_busca, posicao, largura, perfil, aro).
"""
import logging
import unicodedata
from datetime import datetime, timezone

from agente_2w.db.client import supabase

logger = logging.getLogger(__name__)

_TABELA = "compatibilidade_web_cache"


def _normalizar(texto: str) -> str:
    """Lowercase + remove acentos para chave de cache."""
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = sem_acento.encode("ascii", "ignore").decode("ascii")
    return sem_acento.strip().lower()


def buscar(termo: str, posicao: str | None = None) -> list[dict]:
    """Busca no cache pelo termo normalizado e posição opcional.

    Retorna lista de dicts com chaves: moto_nome, posicao, largura, perfil, aro.
    Lista vazia se não houver entradas.
    """
    if not termo:
        return []

    chave = _normalizar(termo)
    try:
        query = (
            supabase.table(_TABELA)
            .select("moto_nome, posicao, largura, perfil, aro")
            .eq("termo_busca", chave)
        )
        if posicao:
            query = query.eq("posicao", posicao.lower())

        res = query.execute()

        if res.data:
            # Atualiza timestamp de último acesso (fire-and-forget)
            try:
                supabase.table(_TABELA).update(
                    {"atualizado_em": datetime.now(timezone.utc).isoformat()}
                ).eq("termo_busca", chave).execute()
            except Exception:
                pass
            return res.data
        return []
    except Exception:
        logger.exception("Erro ao buscar cache compat para termo '%s'", termo)
        return []


def salvar(
    termo_original: str,
    moto_nome: str | None,
    posicao: str | None,
    largura: int | None,
    perfil: int | None,
    aro: int | None,
    origem: str = "web",
    marca_moto: str | None = None,
    ano_moto: int | None = None,
) -> None:
    """Salva (ou atualiza) entrada no cache de compatibilidade."""
    if not termo_original:
        return

    chave = _normalizar(termo_original)
    try:
        supabase.table(_TABELA).upsert({
            "termo_busca": chave,
            "moto_nome": moto_nome,
            "marca_moto": marca_moto,
            "ano_moto": ano_moto,
            "posicao": posicao.lower() if posicao else None,
            "largura": largura,
            "perfil": perfil,
            "aro": aro,
            "origem": origem,
            "consultado_em": datetime.now(timezone.utc).isoformat(),
            "atualizado_em": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="termo_busca,posicao,largura,perfil,aro").execute()
        logger.info(
            "Cache compat salvo: '%s' (%s %s) → %s %s/%s-%s [%s]",
            termo_original, marca_moto, ano_moto, posicao, largura, perfil, aro, origem,
        )
    except Exception:
        logger.exception("Erro ao salvar cache compat para '%s'", termo_original)


def salvar_lista(
    termo_original: str,
    moto_nome: str | None,
    medidas: list[dict],
    origem: str = "web",
    marca_moto: str | None = None,
    ano_moto: int | None = None,
) -> None:
    """Salva múltiplas medidas de uma vez.

    Cada item em medidas deve ter: posicao, largura, perfil, aro.
    """
    for m in medidas:
        salvar(
            termo_original=termo_original,
            moto_nome=moto_nome,
            posicao=m.get("posicao"),
            largura=m.get("largura"),
            perfil=m.get("perfil"),
            aro=m.get("aro"),
            origem=origem,
            marca_moto=marca_moto,
            ano_moto=ano_moto,
        )
