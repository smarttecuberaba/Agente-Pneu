"""Aplicacao de mudancas em itens provisorios com auto-enriquecimento.

Quando a IA sugere itens novos sem pneu_id (ou com UUID malformado), este
modulo tenta completar a informacao a partir dos resultados de tool do turno
(pneus encontrados na busca). Tambem preenche preco_unitario_sugerido quando
a IA esquece de repassar.

Tambem trata acoes de confirmacao/rejeicao/cancelamento/atualizacao com
auto-correcao quando a IA envia pneu_id no lugar de item_provisorio_id.
"""
import logging
from uuid import UUID

from agente_2w.db import item_provisorio_repo
from agente_2w.enums.enums import StatusItemProvisorio
from agente_2w.schemas.item_provisorio import ItemProvisorioCreate

logger = logging.getLogger(__name__)


def _aplicar_mudancas_itens(sessao_id: UUID, mudancas, pneus_encontrados: list[dict] | None = None) -> None:
    """Aplica mudancas propostas pela IA em itens provisorios.

    pneus_encontrados: pneu_ids extraidos das tools (fallback se IA nao passar UUID).
    """
    pneus_encontrados = pneus_encontrados or []

    for mudanca in mudancas:
        try:
            if mudanca.acao == "criar":
                dados = mudanca.dados or {}
                pneu_id_raw = dados.get("pneu_id")
                posicao = dados.get("posicao")

                # Validar UUID antes de usar — rejeitar silenciosamente se malformado
                pneu_uuid = None
                if pneu_id_raw:
                    try:
                        pneu_uuid = UUID(str(pneu_id_raw))
                    except (ValueError, AttributeError):
                        logger.warning(
                            "pneu_id invalido ignorado: '%s'. Tentando auto-enriquecer.",
                            pneu_id_raw,
                        )

                # --- AUTO-ENRIQUECIMENTO: se IA nao passou UUID valido, buscar nos resultados de tool ---
                if pneu_uuid is None and pneus_encontrados:
                    # Deduplica por pneu_id
                    vistos = set()
                    unicos = []
                    for p in pneus_encontrados:
                        pid = p.get("pneu_id")
                        if pid and pid not in vistos:
                            vistos.add(pid)
                            unicos.append(p)

                    match = None
                    # Tenta match por posicao
                    if posicao:
                        match = next(
                            (p for p in unicos if p.get("posicao") and posicao in str(p["posicao"])),
                            None,
                        )
                    # Se so tem 1 pneu nos resultados, usa direto
                    if not match and len(unicos) == 1:
                        match = unicos[0]

                    if match:
                        try:
                            pneu_uuid = UUID(str(match["pneu_id"]))
                            logger.info(
                                "pneu_id auto-enriquecido do resultado de tool: %s",
                                pneu_uuid,
                            )
                        except (ValueError, AttributeError):
                            pass

                # --- AUTO-ENRIQUECIMENTO DE PRECO: preencher preco mesmo quando modelo ja passou pneu_id ---
                if pneu_uuid and not dados.get("preco_unitario_sugerido") and pneus_encontrados:
                    preco_match = next(
                        (p for p in pneus_encontrados
                         if p.get("pneu_id") and str(p["pneu_id"]) == str(pneu_uuid) and p.get("preco_venda")),
                        None,
                    )
                    if preco_match:
                        dados["preco_unitario_sugerido"] = float(preco_match["preco_venda"])
                        logger.info(
                            "preco_unitario_sugerido auto-enriquecido: %s (pneu_id=%s)",
                            preco_match["preco_venda"], pneu_uuid,
                        )

                # --- FALLBACK DE PRECO: buscar direto no DB se nao encontrou nos resultados ---
                # Ocorre quando buscar_pneus_por_moto foi usado (nao retorna preco) e
                # consultar_estoque foi chamado mas seu resultado foi descartado pela
                # deduplicacao de pneu_id em _persistir_pneus_encontrados.
                if pneu_uuid and not dados.get("preco_unitario_sugerido"):
                    try:
                        from agente_2w.db import catalogo_repo as _catalogo_repo
                        estoque_db = _catalogo_repo.buscar_estoque_por_pneu(pneu_uuid)
                        if estoque_db and estoque_db.preco_venda:
                            dados["preco_unitario_sugerido"] = float(estoque_db.preco_venda)
                            logger.info(
                                "preco_unitario_sugerido carregado do DB (fallback): %s (pneu_id=%s)",
                                estoque_db.preco_venda, pneu_uuid,
                            )
                        else:
                            logger.warning(
                                "Nao foi possivel obter preco para pneu_id=%s "
                                "(sem estoque no DB). Item sera criado sem preco.",
                                pneu_uuid,
                            )
                    except Exception:
                        logger.exception(
                            "Falha no fallback de preco para pneu_id=%s", pneu_uuid
                        )

                # Se tem pneu_id valido, criar ja como selecionado_cliente
                status_inicial = (
                    StatusItemProvisorio.selecionado_cliente
                    if pneu_uuid
                    else StatusItemProvisorio.sugerido
                )

                item_provisorio_repo.criar_item(ItemProvisorioCreate(
                    sessao_chat_id=sessao_id,
                    status_item=status_inicial,
                    pneu_id=pneu_uuid,
                    posicao=posicao,
                    quantidade=dados.get("quantidade", 1),
                    preco_unitario_sugerido=dados.get("preco_unitario_sugerido"),
                    observacao=dados.get("observacao"),
                ))
                logger.info(
                    "Item provisorio criado para sessao %s (pneu_id=%s, status=%s)",
                    sessao_id, pneu_uuid, status_inicial.value,
                )

            elif mudanca.acao in ("confirmar", "rejeitar", "cancelar", "atualizar"):
                if not mudanca.item_provisorio_id:
                    logger.warning("Mudanca '%s' sem item_provisorio_id", mudanca.acao)
                    continue

                try:
                    item_id = UUID(mudanca.item_provisorio_id)
                except (ValueError, AttributeError):
                    logger.warning(
                        "Mudanca '%s': item_provisorio_id '%s' nao e UUID valido — ignorando",
                        mudanca.acao, mudanca.item_provisorio_id,
                    )
                    continue

                # Auto-correcao: modelo as vezes passa pneu_id no lugar de item_provisorio_id
                itens_ativos = item_provisorio_repo.listar_itens_ativos_por_sessao(sessao_id)
                item_direto = next((i for i in itens_ativos if i.id == item_id), None)
                if item_direto is None:
                    candidatos_pneu = [
                        i for i in itens_ativos
                        if i.pneu_id and str(i.pneu_id) == str(item_id)
                    ]
                    # Quando ha multiplos itens com o mesmo pneu_id (ex: CB300 e Fazer
                    # com pneu 110/70-17), usar o mais recente para nao confirmar item
                    # de outra moto.
                    item_por_pneu = (
                        max(candidatos_pneu, key=lambda i: i.criado_em)
                        if candidatos_pneu else None
                    )
                    if item_por_pneu:
                        logger.info(
                            "Auto-correcao item_provisorio_id: '%s' era pneu_id, "
                            "usando item mais recente %s (de %d candidatos)",
                            item_id, item_por_pneu.id, len(candidatos_pneu),
                        )
                        item_id = item_por_pneu.id
                    elif len(itens_ativos) == 1:
                        logger.info(
                            "Auto-correcao item_provisorio_id: UUID '%s' nao encontrado, "
                            "usando unico item ativo %s",
                            item_id, itens_ativos[0].id,
                        )
                        item_id = itens_ativos[0].id
                    else:
                        logger.warning(
                            "Mudanca '%s': item_provisorio_id '%s' nao encontrado e "
                            "ha %d itens ativos — impossivel auto-corrigir",
                            mudanca.acao, item_id, len(itens_ativos),
                        )
                        continue

                if mudanca.acao == "confirmar":
                    item_provisorio_repo.atualizar_status_item(
                        item_id, StatusItemProvisorio.selecionado_cliente,
                    )
                elif mudanca.acao == "rejeitar":
                    item_provisorio_repo.atualizar_status_item(
                        item_id, StatusItemProvisorio.rejeitado,
                    )
                elif mudanca.acao == "cancelar":
                    item_provisorio_repo.atualizar_status_item(
                        item_id, StatusItemProvisorio.cancelado,
                    )
                elif mudanca.acao == "atualizar":
                    dados = mudanca.dados or {}
                    if dados.get("pneu_id"):
                        try:
                            item_provisorio_repo.vincular_pneu(
                                item_id, UUID(dados["pneu_id"]),
                            )
                        except (ValueError, AttributeError):
                            logger.warning("pneu_id invalido em atualizar: '%s'", dados["pneu_id"])
                    if dados.get("status_item"):
                        status_str = dados["status_item"]
                        # Bloquear IA de setar promovido — exclusivo do promotor
                        if status_str == "promovido":
                            logger.warning(
                                "IA tentou setar status_item=promovido no item %s. Bloqueado.",
                                item_id,
                            )
                        else:
                            status = StatusItemProvisorio(status_str)
                            item_provisorio_repo.atualizar_status_item(item_id, status)

        except Exception:
            logger.exception("Erro ao aplicar mudanca item '%s'", mudanca.acao)
