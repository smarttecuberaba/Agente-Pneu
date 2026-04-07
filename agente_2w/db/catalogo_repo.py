import logging
from uuid import UUID

from agente_2w.db.client import supabase
from agente_2w.db.exceptions import RegistroNaoEncontrado, RepositoryError
from agente_2w.schemas.pneu import Pneu
from agente_2w.schemas.moto import Moto
from agente_2w.schemas.estoque import Estoque

logger = logging.getLogger(__name__)


# --- Pneus ---

def buscar_pneu_por_id(pneu_id: UUID) -> Pneu | None:
    try:
        resultado = (
            supabase.table("pneu")
            .select("*")
            .eq("id", str(pneu_id))
            .eq("ativo", True)
            .maybe_single()
            .execute()
        )
        if resultado is None or resultado.data is None:
            return None
        return Pneu(**resultado.data)
    except Exception as e:
        raise RegistroNaoEncontrado("pneu", str(pneu_id)) from e


def buscar_pneus_por_dimensoes(
    largura: int | None = None,
    perfil: int | None = None,
    aro: int | None = None,
) -> list[dict]:
    try:
        query = supabase.table("catalogo_agente").select("*").gt("disponivel_real", 0)
        if largura is not None:
            query = query.eq("largura", largura)
        if perfil is not None:
            query = query.eq("perfil", perfil)
        if aro is not None:
            query = query.eq("aro", aro)
        resultado = query.execute()
        return resultado.data
    except Exception as e:
        raise RepositoryError("busca", "catalogo_agente", str(e)) from e


def buscar_pneus_por_medida_texto(medida: str) -> list[dict]:
    try:
        resultado = (
            supabase.table("catalogo_agente")
            .select("*")
            .ilike("medida", f"%{medida}%")
            .gt("disponivel_real", 0)
            .execute()
        )
        return resultado.data
    except Exception as e:
        raise RepositoryError("busca", "catalogo_agente", f"medida={medida}: {e}") from e


def buscar_pneus_por_marca_modelo(termo: str) -> list[dict]:
    try:
        resultado = (
            supabase.rpc("buscar_pneu_por_texto", {"termo_busca": termo})
            .execute()
        )
        return resultado.data
    except Exception as e:
        raise RepositoryError("busca", "rpc:buscar_pneu_por_texto", str(e)) from e


# --- Motos ---

def buscar_moto_por_id(moto_id: UUID) -> Moto | None:
    try:
        resultado = (
            supabase.table("moto")
            .select("*")
            .eq("id", str(moto_id))
            .maybe_single()
            .execute()
        )
        if resultado is None or resultado.data is None:
            return None
        return Moto(**resultado.data)
    except Exception as e:
        raise RegistroNaoEncontrado("moto", str(moto_id)) from e


def buscar_motos_por_texto(termo: str) -> list[dict]:
    try:
        resultado = (
            supabase.rpc("buscar_moto_por_texto", {"termo_busca": termo})
            .execute()
        )
        return resultado.data
    except Exception as e:
        raise RepositoryError("busca", "rpc:buscar_moto_por_texto", str(e)) from e


# --- Medida Moto ---

def listar_medidas_por_moto(moto_id: UUID) -> list[dict]:
    try:
        resultado = (
            supabase.table("medida_moto")
            .select("*")
            .eq("moto_id", str(moto_id))
            .execute()
        )
        return resultado.data
    except Exception as e:
        raise RegistroNaoEncontrado("medida_moto", str(moto_id)) from e


# --- Compatibilidade ---

def buscar_compatibilidade_por_moto(moto_id: UUID) -> list[dict]:
    try:
        resultado = (
            supabase.table("compatibilidade_moto_pneu")
            .select("*")
            .eq("moto_id", str(moto_id))
            .execute()
        )
        return resultado.data
    except Exception as e:
        raise RepositoryError("busca", "compatibilidade_moto_pneu", str(e)) from e


def buscar_compatibilidade_por_moto_texto(termo: str) -> list[dict]:
    motos = buscar_motos_por_texto(termo)
    if not motos:
        return []
    resultados = []
    for moto in motos:
        compat = buscar_compatibilidade_por_moto(UUID(moto["id"]))
        resultados.extend(compat)

    # Enriquecer com info de estoque para evitar sugerir pneus sem disponibilidade
    pneu_ids = list({r["pneu_id"] for r in resultados if r.get("pneu_id")})
    estoque_map: dict[str, bool] = {}
    for pid in pneu_ids:
        estoque = buscar_estoque_por_pneu(UUID(pid))
        if estoque:
            disponivel = estoque.quantidade_disponivel - estoque.reservado
            estoque_map[pid] = disponivel > 0
        else:
            estoque_map[pid] = False

    for r in resultados:
        pid = r.get("pneu_id")
        r["em_estoque"] = estoque_map.get(pid, False)

    return resultados


# --- Estoque ---

def buscar_estoque_por_pneu(pneu_id: UUID) -> Estoque | None:
    try:
        resultado = (
            supabase.table("estoque")
            .select("*")
            .eq("pneu_id", str(pneu_id))
            .maybe_single()
            .execute()
        )
        if resultado is None or resultado.data is None:
            return None
        return Estoque(**resultado.data)
    except Exception as e:
        raise RegistroNaoEncontrado("estoque", str(pneu_id)) from e


def incrementar_reservado(pneu_id: UUID, quantidade: int) -> None:
    """Reserva quantidade no estoque de forma atomica (reservado += quantidade)."""
    try:
        supabase.rpc("atualizar_reservado_estoque", {
            "p_pneu_id": str(pneu_id),
            "p_delta": quantidade,
        }).execute()
        logger.debug("Reservado +%d para pneu %s", quantidade, pneu_id)
    except Exception:
        logger.exception("Falha ao incrementar reservado pneu %s", pneu_id)


def decrementar_reservado(pneu_id: UUID, quantidade: int) -> None:
    """Libera quantidade reservada no estoque (reservado -= quantidade, min 0)."""
    try:
        supabase.rpc("atualizar_reservado_estoque", {
            "p_pneu_id": str(pneu_id),
            "p_delta": -quantidade,
        }).execute()
        logger.debug("Reservado -%d para pneu %s", quantidade, pneu_id)
    except Exception:
        logger.exception("Falha ao decrementar reservado pneu %s", pneu_id)
