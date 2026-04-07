"""Repositório para log_demanda_pneu — analytics de demanda por pneus.

Registra toda intenção de busca de pneu por clientes, independente de
ter estoque ou não, e se converteu em pedido. Base para relatórios de
sazonalidade, falta de estoque e taxa de conversão.
"""

import logging
from uuid import UUID

from agente_2w.db.client import supabase

logger = logging.getLogger(__name__)


def registrar_busca(
    moto: str,
    posicao: str,
    tinha_estoque: bool,
    fonte_resolucao: str,
    largura: int | None = None,
    perfil: int | None = None,
    aro: int | None = None,
    marca_moto: str | None = None,
    ano_moto: int | None = None,
    canal: str | None = None,
    sessao_id: UUID | None = None,
    cliente_id: UUID | None = None,
    preco_encontrado: float | None = None,
) -> UUID | None:
    """Registra uma busca de pneu no log de demanda.

    Fail-safe: nunca levanta exceção — erro só vai pro log.

    Parâmetros:
        moto: nome/modelo da moto buscada
        posicao: 'dianteiro' | 'traseiro'
        tinha_estoque: True se encontrou pneu disponível no catálogo
        fonte_resolucao: 'catalogo' | 'cache' | 'web'
        largura/perfil/aro: medida do pneu encontrado (quando disponível)
        marca_moto: marca extraída do termo (ex: 'Yamaha')
        ano_moto: ano extraído do termo (ex: 2024)
        canal: canal de atendimento ('whatsapp' | 'web' | 'cli')
        sessao_id: UUID da sessão de chat
        cliente_id: UUID do cliente (quando disponível)
        preco_encontrado: preço do primeiro pneu retornado

    Retorna UUID do registro criado, ou None em caso de falha.
    """
    try:
        payload: dict = {
            "moto": moto,
            "posicao": posicao,
            "tinha_estoque": tinha_estoque,
            "fonte_resolucao": fonte_resolucao,
        }
        if largura is not None:
            payload["largura"] = largura
        if perfil is not None:
            payload["perfil"] = perfil
        if aro is not None:
            payload["aro"] = aro
        if marca_moto:
            payload["marca_moto"] = marca_moto
        if ano_moto:
            payload["ano_moto"] = ano_moto
        if canal:
            payload["canal"] = canal
        if sessao_id:
            payload["sessao_id"] = str(sessao_id)
        if cliente_id:
            payload["cliente_id"] = str(cliente_id)
        if preco_encontrado is not None:
            payload["preco_encontrado"] = float(preco_encontrado)

        resp = supabase.table("log_demanda_pneu").insert(payload).execute()

        if resp.data:
            registro_id = resp.data[0].get("id")
            logger.debug(
                "log_demanda_pneu registrado: %s (%s) estoque=%s fonte=%s medida=%s/%s-%s",
                moto, posicao, tinha_estoque, fonte_resolucao, largura, perfil, aro,
            )
            return UUID(registro_id) if registro_id else None

    except Exception:
        logger.exception("Falha ao registrar log_demanda_pneu: moto=%s posicao=%s", moto, posicao)

    return None


def marcar_converteu_pedido(sessao_id: UUID, pedido_id: UUID) -> None:
    """Marca todas as buscas da sessão como convertidas em pedido.

    Chamado após confirmação do pedido no promotor.
    Fail-safe: nunca levanta exceção — erro só vai pro log.
    """
    try:
        supabase.table("log_demanda_pneu").update({
            "converteu_pedido": True,
            "pedido_id": str(pedido_id),
        }).eq("sessao_id", str(sessao_id)).execute()

        logger.debug(
            "log_demanda_pneu: marcado converteu_pedido=True para sessao=%s pedido=%s",
            sessao_id, pedido_id,
        )
    except Exception:
        logger.exception(
            "Falha ao marcar converteu_pedido: sessao=%s pedido=%s",
            sessao_id, pedido_id,
        )
