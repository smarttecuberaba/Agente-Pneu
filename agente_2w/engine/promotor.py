"""Promotor — converte itens provisorios validados em pedido oficial.

Usa RPC transacional do Supabase para garantir atomicidade:
pedido + itens + promocao de status acontecem numa unica transacao.
"""

import logging
import unicodedata
from uuid import UUID
from decimal import Decimal

from agente_2w.db import (
    sessao_repo,
    item_provisorio_repo,
    contexto_repo,
    catalogo_repo,
    cliente_repo,
    pedido_repo,
    log_demanda_pneu_repo,
)
from agente_2w.db.client import supabase
from agente_2w.enums.enums import (
    EtapaFluxo,
    StatusItemProvisorio,
    TipoEntrega,
    FormaPagamento,
)
from agente_2w.schemas.pedido import Pedido
from agente_2w.constantes import ChaveContexto

logger = logging.getLogger(__name__)


def _calcular_segmento(total_pedidos: int, valor_total: Decimal) -> str:
    """Regra de negocio: classifica cliente por historico de compras."""
    if total_pedidos >= 5 or valor_total >= Decimal("500"):
        return "vip"
    if total_pedidos >= 1:
        return "recorrente"
    return "novo"


def _atualizar_stats_cliente(cliente_id, valor_pedido: Decimal) -> None:
    """Incrementa contadores do cliente apos pedido confirmado."""
    try:
        cliente = cliente_repo.buscar_cliente_por_id(cliente_id)
        if not cliente:
            return
        novo_total_pedidos = cliente.total_pedidos + 1
        novo_valor_total = cliente.valor_total_gasto + valor_pedido
        novo_segmento = _calcular_segmento(novo_total_pedidos, novo_valor_total)
        from datetime import datetime, timezone
        cliente_repo.atualizar_cliente(cliente_id, {
            "total_pedidos": novo_total_pedidos,
            "valor_total_gasto": str(novo_valor_total),
            "ultima_compra_em": datetime.now(timezone.utc).isoformat(),
            "segmento": novo_segmento,
        })
        logger.info(
            "Stats cliente %s atualizados: pedidos=%d, total=%.2f, segmento=%s",
            cliente_id, novo_total_pedidos, novo_valor_total, novo_segmento,
        )
    except Exception:
        logger.exception("Falha ao atualizar stats do cliente %s", cliente_id)


def _normalizar(valor: str) -> str:
    """Remove acentos e converte para minúsculo. 'cartão' → 'cartao'."""
    sem_acento = unicodedata.normalize("NFD", valor)
    sem_acento = sem_acento.encode("ascii", "ignore").decode("ascii")
    return sem_acento.strip().lower()


class ErroPromocao(Exception):
    """Pre-condicao do promotor nao atendida."""


def cancelar_pedido_sessao(sessao_id: UUID) -> bool:
    """Cancela o pedido da sessao, libera estoque reservado e reverte stats do cliente.

    Retorna True se cancelou, False se nao havia pedido para cancelar.
    """
    from datetime import datetime, timezone

    pedido = pedido_repo.buscar_pedido_por_sessao(sessao_id)
    if not pedido:
        logger.warning("cancelar_pedido_sessao: nenhum pedido encontrado para sessao %s", sessao_id)
        return False

    if pedido.status_pedido.value == "cancelado":
        logger.info("Pedido %s ja esta cancelado", pedido.id)
        return False

    pedido_repo.cancelar_pedido(pedido.id)
    logger.info("Pedido %s cancelado", pedido.id)

    # Liberar estoque reservado
    try:
        itens = pedido_repo.listar_itens_pedido(pedido.id)
        for item in itens:
            catalogo_repo.decrementar_reservado(item.pneu_id, item.quantidade)
        logger.info("Estoque liberado: %d itens do pedido %s", len(itens), pedido.id)
    except Exception:
        logger.exception("Falha ao liberar estoque do pedido %s", pedido.id)

    # Reverter stats do cliente
    try:
        cliente = cliente_repo.buscar_cliente_por_id(pedido.cliente_id)
        if cliente and cliente.total_pedidos > 0:
            novo_total = cliente.total_pedidos - 1
            novo_valor = max(Decimal("0"), cliente.valor_total_gasto - pedido.valor_total)
            novo_segmento = _calcular_segmento(novo_total, novo_valor)
            cliente_repo.atualizar_cliente(pedido.cliente_id, {
                "total_pedidos": novo_total,
                "valor_total_gasto": str(novo_valor),
                "segmento": novo_segmento,
            })
            logger.info(
                "Stats cliente revertidos: pedidos=%d, valor=%.2f, segmento=%s",
                novo_total, novo_valor, novo_segmento,
            )
    except Exception:
        logger.exception("Falha ao reverter stats do cliente")

    return True


def alterar_pedido_sessao(sessao_id: UUID) -> bool:
    """Sincroniza forma_pagamento, tipo_entrega e endereco_entrega_json do pedido
    com os fatos ativos da sessao.

    Chamado apos mudancas de contexto em sessoes com pedido ja criado.
    Retorna True se algum campo foi alterado.
    """
    pedido = pedido_repo.buscar_pedido_por_sessao(sessao_id)
    if not pedido or pedido.status_pedido.value != "confirmado":
        return False

    campos: dict = {}

    fato_pagamento = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.FORMA_PAGAMENTO)
    if fato_pagamento and fato_pagamento.valor_texto:
        nova_forma = _normalizar(fato_pagamento.valor_texto)
        try:
            forma_enum = FormaPagamento(nova_forma)
            if forma_enum != FormaPagamento.a_confirmar and forma_enum != pedido.forma_pagamento:
                campos["forma_pagamento"] = forma_enum.value
        except ValueError:
            pass

    fato_entrega = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.TIPO_ENTREGA)
    if fato_entrega and fato_entrega.valor_texto:
        novo_tipo = _normalizar(fato_entrega.valor_texto)
        try:
            tipo_enum = TipoEntrega(novo_tipo)
            if tipo_enum != TipoEntrega.a_confirmar and tipo_enum != pedido.tipo_entrega:
                campos["tipo_entrega"] = tipo_enum.value
        except ValueError:
            pass

    fato_endereco = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.ENDERECO_ENTREGA)
    if fato_endereco:
        if fato_endereco.valor_json:
            novo_endereco = fato_endereco.valor_json
        elif fato_endereco.valor_texto:
            novo_endereco = {"endereco": fato_endereco.valor_texto}
        else:
            novo_endereco = None
        if novo_endereco and novo_endereco != pedido.endereco_entrega_json:
            campos["endereco_entrega_json"] = novo_endereco

    if not campos:
        return False

    try:
        pedido_repo.atualizar_pedido(pedido.id, campos)
        logger.info("Pedido %s alterado: %s", pedido.id, list(campos.keys()))
        return True
    except Exception:
        logger.exception("Falha ao alterar pedido %s", pedido.id)
        return False


def validar_pre_condicoes(sessao_id: UUID) -> list[str]:
    """Retorna lista de erros. Lista vazia = pode promover."""
    erros: list[str] = []

    sessao = sessao_repo.buscar_sessao_por_id(sessao_id)
    if sessao is None:
        return ["sessao nao encontrada"]

    # 1. Etapa deve ser fechamento
    if sessao.etapa_atual != EtapaFluxo.fechamento:
        erros.append(f"etapa atual e {sessao.etapa_atual.value}, deveria ser fechamento")

    # 2. Cliente resolvido
    if not sessao.cliente_id:
        erros.append("sessao sem cliente resolvido")

    # 3. Pelo menos um item confirmado (selecionado_cliente ou validado) com pneu
    _STATUS_PROMOVIVEL = {StatusItemProvisorio.selecionado_cliente, StatusItemProvisorio.validado}
    itens = item_provisorio_repo.listar_itens_ativos_por_sessao(sessao_id)
    itens_validados = [
        i for i in itens
        if i.status_item in _STATUS_PROMOVIVEL and i.pneu_id is not None
    ]
    if not itens_validados:
        erros.append("nenhum item provisorio confirmado com pneu_id")

    # 4. Tipo entrega definido
    fato_entrega = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.TIPO_ENTREGA)
    if not fato_entrega:
        erros.append("tipo_entrega nao definido")
    elif fato_entrega.valor_texto == TipoEntrega.a_confirmar.value:
        erros.append("tipo_entrega ainda e a_confirmar")

    # 5. Forma pagamento definida
    fato_pagamento = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.FORMA_PAGAMENTO)
    if not fato_pagamento:
        erros.append("forma_pagamento nao definida")
    elif _normalizar(fato_pagamento.valor_texto) == FormaPagamento.a_confirmar.value:
        erros.append("forma_pagamento ainda e a_confirmar")

    # 6. Endereco se entrega + cobertura de frete
    if fato_entrega and fato_entrega.valor_texto == TipoEntrega.entrega.value:
        fato_endereco = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.ENDERECO_ENTREGA)
        if not fato_endereco:
            erros.append("tipo_entrega e entrega mas endereco nao definido")
        fato_nao_coberto = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.FRETE_NAO_COBERTO)
        if fato_nao_coberto:
            erros.append(f"municipio '{fato_nao_coberto.valor_texto}' nao tem cobertura de entrega")

    # 7. Estoque suficiente e preco definido
    for item in itens_validados:
        if not item.preco_unitario_sugerido or item.preco_unitario_sugerido <= 0:
            erros.append(f"item {item.id} sem preco definido")
            continue

        estoque = catalogo_repo.buscar_estoque_por_pneu(item.pneu_id)
        if not estoque:
            erros.append(f"sem registro de estoque para pneu {item.pneu_id}")
        elif (estoque.quantidade_disponivel - estoque.reservado) < item.quantidade:
            erros.append(
                f"estoque insuficiente para pneu {item.pneu_id}: "
                f"disponivel={estoque.quantidade_disponivel - estoque.reservado}, "
                f"necessario={item.quantidade}"
            )

    return erros


def promover_para_pedido(sessao_id: UUID) -> Pedido:
    """Converte itens provisorios validados em pedido oficial.

    Usa RPC transacional — pedido, itens e status sao criados/alterados
    numa unica transacao. Se qualquer parte falhar, nada e persistido.

    Raises:
        ErroPromocao: se pre-condicoes nao forem atendidas.
        ValueError: se a RPC falhar.
    """
    erros = validar_pre_condicoes(sessao_id)
    if erros:
        logger.warning("Pre-condicoes nao atendidas: %s", "; ".join(erros))
        raise ErroPromocao(f"pre-condicoes nao atendidas: {'; '.join(erros)}")

    sessao = sessao_repo.buscar_sessao_por_id(sessao_id)

    # Coletar dados dos fatos
    fato_entrega = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.TIPO_ENTREGA)
    fato_pagamento = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.FORMA_PAGAMENTO)
    fato_endereco = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.ENDERECO_ENTREGA)

    tipo_entrega = TipoEntrega(_normalizar(fato_entrega.valor_texto))
    forma_pagamento = FormaPagamento(_normalizar(fato_pagamento.valor_texto))

    # Endereco pode estar em valor_json (estruturado) ou valor_texto (texto livre)
    endereco_json = None
    if fato_endereco:
        if fato_endereco.valor_json:
            endereco_json = fato_endereco.valor_json
        elif fato_endereco.valor_texto:
            endereco_json = {"endereco": fato_endereco.valor_texto}

    # Itens confirmados (selecionado_cliente ou validado) com pneu_id
    _STATUS_PROMOVIVEL = {StatusItemProvisorio.selecionado_cliente, StatusItemProvisorio.validado}
    itens = item_provisorio_repo.listar_itens_ativos_por_sessao(sessao_id)
    itens_validados = [
        i for i in itens
        if i.status_item in _STATUS_PROMOVIVEL and i.pneu_id is not None
    ]

    # Valor do frete (apenas para entregas)
    valor_frete = Decimal("0")
    if tipo_entrega == TipoEntrega.entrega:
        fato_frete = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.FRETE_VALOR)
        if fato_frete and fato_frete.valor_texto:
            try:
                valor_frete = Decimal(fato_frete.valor_texto)
            except (ValueError, ArithmeticError):
                logger.warning(
                    "valor_frete invalido em fato FRETE_VALOR: '%s'",
                    fato_frete.valor_texto,
                )

    # Montar payload de itens e calcular valor total
    valor_itens = Decimal("0")
    itens_payload = []
    for item in itens_validados:
        preco = item.preco_unitario_sugerido
        subtotal = preco * item.quantidade
        valor_itens += subtotal
        itens_payload.append({
            "pneu_id": str(item.pneu_id),
            "quantidade": item.quantidade,
            "preco_unitario": str(preco),
            "subtotal": str(subtotal),
            "item_provisorio_id": str(item.id),
            "posicao": item.posicao.value if item.posicao else None,
        })

    valor_total = valor_itens + valor_frete

    # Chamar RPC transacional
    logger.info(
        "Chamando RPC promover_para_pedido: sessao=%s, itens=%d, valor_itens=%s, frete=%s, total=%s",
        sessao_id, len(itens_payload), valor_itens, valor_frete, valor_total,
    )

    resultado = supabase.rpc("promover_para_pedido", {
        "p_sessao_id": str(sessao_id),
        "p_cliente_id": str(sessao.cliente_id),
        "p_tipo_entrega": tipo_entrega.value,
        "p_forma_pagamento": forma_pagamento.value,
        "p_valor_total": str(valor_total),
        "p_valor_frete": str(valor_frete),
        "p_endereco_json": endereco_json,
        "p_itens": itens_payload,
    }).execute()

    if not resultado.data:
        raise ValueError("RPC promover_para_pedido retornou vazio")

    rpc_result = resultado.data
    pedido_id = rpc_result.get("pedido_id")

    logger.info(
        "Pedido criado via RPC transacional: %s (valor=%s, itens=%s)",
        pedido_id, valor_total, rpc_result.get("itens_criados"),
    )

    # Reservar estoque para cada item promovido
    for item_payload in itens_payload:
        try:
            catalogo_repo.incrementar_reservado(
                UUID(item_payload["pneu_id"]),
                item_payload["quantidade"],
            )
        except Exception:
            logger.exception("Falha ao reservar estoque pneu %s", item_payload["pneu_id"])

    # Atualizar inteligencia de negocio do cliente
    _atualizar_stats_cliente(sessao.cliente_id, valor_total)

    # Buscar pedido completo para retornar
    pedido = pedido_repo.buscar_pedido_por_id(UUID(pedido_id))
    if pedido is None:
        raise ValueError(f"Pedido {pedido_id} criado pela RPC mas nao encontrado")

    # Marcar buscas da sessão como convertidas em pedido (analytics)
    log_demanda_pneu_repo.marcar_converteu_pedido(sessao_id, pedido.id)

    return pedido
