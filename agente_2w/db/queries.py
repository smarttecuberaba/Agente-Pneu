from uuid import UUID

from agente_2w.db.client import supabase


def contar_registros(tabela: str, filtros: dict | None = None) -> int:
    query = supabase.table(tabela).select("id", count="exact")
    if filtros:
        for campo, valor in filtros.items():
            query = query.eq(campo, str(valor) if isinstance(valor, UUID) else valor)
    resultado = query.execute()
    return resultado.count or 0


def existe_registro(tabela: str, filtros: dict) -> bool:
    return contar_registros(tabela, filtros) > 0


def buscar_por_id(tabela: str, registro_id: UUID) -> dict | None:
    resultado = (
        supabase.table(tabela)
        .select("*")
        .eq("id", str(registro_id))
        .maybe_single()
        .execute()
    )
    return resultado.data
