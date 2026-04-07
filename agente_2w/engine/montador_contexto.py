from uuid import UUID
from datetime import datetime, timezone

from agente_2w.db import sessao_repo, mensagem_repo, contexto_repo, item_provisorio_repo, cliente_repo, pedido_repo, catalogo_repo, area_entrega_repo, config_loja_repo
from agente_2w.engine.pendencias import acoes_permitidas, pendencias_da_etapa
from agente_2w.enums.enums import StatusSessao, StatusItemProvisorio
from agente_2w.constantes import ChaveContexto
from agente_2w.schemas.contexto_executavel import (
    ContextoExecutavel,
    SessaoContexto,
    ClienteContexto,
    BloqueioAtivo,
    MensagemRecente,
    FatoAtivo,
    FreteContexto,
    ItemProvisorioContexto,
    ItemUltimoPedidoContexto,
    UltimoPedidoContexto,
    ItemPedidoSessaoContexto,
    PedidoSessaoContexto,
    Pendencia,
    ResumoOperacional,
    Metadados,
)


def montar_contexto(sessao_id: UUID) -> ContextoExecutavel:
    sessao = sessao_repo.buscar_sessao_por_id(sessao_id)
    if sessao is None:
        raise ValueError(f"sessao {sessao_id} nao encontrada")

    # Sessao
    sessao_ctx = SessaoContexto(
        sessao_id=str(sessao.id),
        canal=sessao.canal,
        contato_externo=sessao.contato_externo,
        etapa_atual=sessao.etapa_atual,
        status_sessao=sessao.status_sessao,
        ultima_interacao_em=sessao.ultima_interacao_em,
    )

    # Cliente
    cliente_ctx = ClienteContexto()
    if sessao.cliente_id:
        cliente = cliente_repo.buscar_cliente_por_id(sessao.cliente_id)
        if cliente:
            # Ultimo pedido confirmado (excluindo a sessao atual)
            ultimo_pedido_ctx = None
            ultimo_pedido = pedido_repo.buscar_ultimo_pedido_confirmado(
                cliente.id, excluir_sessao_id=sessao_id
            )
            if ultimo_pedido:
                itens_pedido = pedido_repo.listar_itens_pedido(ultimo_pedido.id)
                itens_ctx = []
                for item in itens_pedido:
                    pneu = catalogo_repo.buscar_pneu_por_id(item.pneu_id)
                    nome_pneu = pneu.descricao_comercial if pneu else str(item.pneu_id)
                    itens_ctx.append(ItemUltimoPedidoContexto(
                        pneu_nome=nome_pneu,
                        posicao=item.posicao.value if item.posicao else None,
                        quantidade=item.quantidade,
                        preco_unitario=item.preco_unitario,
                    ))
                ultimo_pedido_ctx = UltimoPedidoContexto(
                    data=ultimo_pedido.criado_em,
                    valor_total=ultimo_pedido.valor_total,
                    forma_pagamento=ultimo_pedido.forma_pagamento.value,
                    tipo_entrega=ultimo_pedido.tipo_entrega.value,
                    itens=itens_ctx,
                )

            cliente_ctx = ClienteContexto(
                cliente_id=str(cliente.id),
                nome=cliente.nome,
                telefone=cliente.telefone,
                resolvido=True,
                segmento=cliente.segmento,
                total_pedidos=cliente.total_pedidos,
                valor_total_gasto=cliente.valor_total_gasto,
                ultima_compra_em=cliente.ultima_compra_em,
                municipio=cliente.municipio,
                bairro=cliente.bairro,
                ultimo_pedido=ultimo_pedido_ctx,
            )

    # Bloqueios
    bloqueios: list[BloqueioAtivo] = []
    if sessao.status_sessao == StatusSessao.bloqueada and sessao.codigo_motivo:
        bloqueios.append(BloqueioAtivo(
            codigo_motivo=sessao.codigo_motivo,
            mensagem_motivo=sessao.mensagem_motivo or "",
            campo_relacionado=sessao.campo_relacionado,
            acao_bloqueada=sessao.acao_bloqueada or "",
        ))

    # Mensagens recentes
    mensagens_db = mensagem_repo.listar_mensagens_por_sessao(sessao_id, limite=20)
    mensagens_recentes = [
        MensagemRecente(
            mensagem_id=str(m.id),
            direcao=m.direcao.value,
            remetente=m.remetente.value,
            conteudo_texto=m.conteudo_texto,
            criado_em=m.criado_em,
        )
        for m in mensagens_db
    ]

    # Fatos ativos
    fatos_db = contexto_repo.listar_fatos_ativos(sessao_id)
    fatos_ativos = [
        FatoAtivo(
            chave=f.chave,
            valor=f.valor_texto if f.valor_texto else f.valor_json,
            tipo_de_verdade=f.tipo_de_verdade,
            nivel_confirmacao=f.nivel_confirmacao,
            fonte=f.fonte,
            mensagem_chat_id=str(f.mensagem_chat_id) if f.mensagem_chat_id else None,
            item_provisorio_id=str(f.item_provisorio_id) if f.item_provisorio_id else None,
            coletado_em=f.coletado_em,
        )
        for f in fatos_db
    ]

    # Itens provisorios
    itens_db = item_provisorio_repo.listar_itens_ativos_por_sessao(sessao_id)
    itens_provisorios = [
        ItemProvisorioContexto(
            item_provisorio_id=str(item.id),
            pneu_id=str(item.pneu_id) if item.pneu_id else None,
            descricao_contextual=item.observacao or f"item {item.status_item.value}",
            posicao=item.posicao.value if item.posicao else None,
            quantidade=item.quantidade,
            status_item=item.status_item,
            preco_unitario_sugerido=item.preco_unitario_sugerido,
            cliente_confirmou=item.cliente_confirmou_em is not None,
            validado_backend=item.validado_backend_em is not None,
        )
        for item in itens_db
    ]

    # Pendencias
    pendencias_etapa = pendencias_da_etapa(sessao.etapa_atual)
    pendencias = [
        Pendencia(
            codigo=p["codigo"],
            descricao=p["descricao"],
            campo_relacionado=p.get("campo_relacionado"),
            obrigatoria_para=p["obrigatoria_para"],
        )
        for p in pendencias_etapa
    ]

    # Acoes permitidas
    acoes = acoes_permitidas(sessao.etapa_atual)

    # Resumo operacional
    tem_item_validado = any(
        item.status_item in (StatusItemProvisorio.validado, StatusItemProvisorio.selecionado_cliente)
        and item.pneu_id is not None
        for item in itens_db
    )

    chaves_ativas = {f.chave for f in fatos_db}
    tem_entrega = ChaveContexto.TIPO_ENTREGA in chaves_ativas
    tem_pagamento = ChaveContexto.FORMA_PAGAMENTO in chaves_ativas

    # pode_avancar depende da etapa atual:
    # - confirmacao_item: precisa de item validado
    # - entrega_pagamento: precisa de item + entrega + pagamento
    # - demais: item validado + nao bloqueada
    from agente_2w.enums.enums import EtapaFluxo
    _nao_bloqueada = sessao.status_sessao != StatusSessao.bloqueada
    if sessao.etapa_atual == EtapaFluxo.entrega_pagamento:
        pode_avancar = tem_item_validado and tem_entrega and tem_pagamento and _nao_bloqueada
    else:
        pode_avancar = tem_item_validado and _nao_bloqueada

    resumo = ResumoOperacional(
        tem_item_validado=tem_item_validado,
        tem_entrega_definida=tem_entrega,
        tem_pagamento_definido=tem_pagamento,
        pode_avancar_etapa=pode_avancar,
    )

    # Frete (se calculado)
    frete_ctx = None
    fato_frete = next((f for f in fatos_db if f.chave == ChaveContexto.FRETE_VALOR), None)
    fato_nao_coberto = next((f for f in fatos_db if f.chave == ChaveContexto.FRETE_NAO_COBERTO), None)
    if fato_frete and fato_frete.valor_texto:
        from decimal import Decimal
        municipio_frete = (
            cliente_ctx.municipio
            or next((f.valor_texto for f in fatos_db if f.chave == ChaveContexto.MUNICIPIO), None)
        )
        frete_ctx = FreteContexto(
            municipio=municipio_frete or "desconhecido",
            coberto=True,
            valor_frete=Decimal(fato_frete.valor_texto),
            bairro=cliente_ctx.bairro,
        )
    elif fato_nao_coberto and fato_nao_coberto.valor_texto:
        frete_ctx = FreteContexto(
            municipio=fato_nao_coberto.valor_texto,
            coberto=False,
        )

    # Tabela de fretes (exposta para IA responder proativamente)
    tabela_fretes = area_entrega_repo.buscar_tabela_fretes()

    # Configuracoes da loja (endereco, horario, montagem, garantia, etc)
    config_loja = config_loja_repo.buscar_config_loja()

    # Pedido ja criado nesta sessao (se existir)
    pedido_sessao_ctx = None
    pedido_sessao = pedido_repo.buscar_pedido_por_sessao(sessao_id)
    if pedido_sessao and pedido_sessao.status_pedido.value == "confirmado":
        itens_pedido_sessao = pedido_repo.listar_itens_pedido(pedido_sessao.id)
        itens_pedido_ctx = []
        for item in itens_pedido_sessao:
            pneu = catalogo_repo.buscar_pneu_por_id(item.pneu_id)
            nome_pneu = pneu.descricao_comercial if pneu else str(item.pneu_id)
            itens_pedido_ctx.append(ItemPedidoSessaoContexto(
                pneu_nome=nome_pneu,
                posicao=item.posicao.value if item.posicao else None,
                quantidade=item.quantidade,
                preco_unitario=item.preco_unitario,
            ))
        pedido_sessao_ctx = PedidoSessaoContexto(
            pedido_id=str(pedido_sessao.id),
            numero_pedido=pedido_sessao.numero_pedido,
            status_pedido=pedido_sessao.status_pedido.value,
            valor_total=pedido_sessao.valor_total,
            valor_frete=pedido_sessao.valor_frete,
            forma_pagamento=pedido_sessao.forma_pagamento.value,
            tipo_entrega=pedido_sessao.tipo_entrega.value,
            endereco_entrega_json=pedido_sessao.endereco_entrega_json,
            itens=itens_pedido_ctx,
            criado_em=pedido_sessao.criado_em,
        )

    # Alertas contextuais — avisa a IA sobre dados ja registrados para evitar
    # perguntas redundantes e loops de confirmacao
    alertas: list[str] = []

    # Alertas de chaves simples (valor texto + sufixo customizado)
    _ALERTAS_SIMPLES = [
        (ChaveContexto.NOME_CLIENTE, "NAO pergunte o nome de novo"),
        (ChaveContexto.TIPO_ENTREGA, "NAO pergunte de novo"),
        (ChaveContexto.FORMA_PAGAMENTO, "NAO pergunte de novo"),
        (ChaveContexto.MUNICIPIO, "NAO pergunte o municipio de novo"),
    ]
    for chave, sufixo in _ALERTAS_SIMPLES:
        if chave in chaves_ativas:
            fato = next((f for f in fatos_db if f.chave == chave), None)
            val = fato.valor_texto if fato else ""
            alertas.append(f"{chave} ja registrado como '{val}' — {sufixo}")

    # Alerta de endereco_entrega — logica especial (texto OU json estruturado)
    if ChaveContexto.ENDERECO_ENTREGA in chaves_ativas:
        fato_end = next((f for f in fatos_db if f.chave == ChaveContexto.ENDERECO_ENTREGA), None)
        if fato_end and fato_end.valor_texto:
            end_val = fato_end.valor_texto
        elif fato_end and fato_end.valor_json and isinstance(fato_end.valor_json, dict):
            partes = [
                fato_end.valor_json.get("logradouro", ""),
                fato_end.valor_json.get("numero", ""),
                fato_end.valor_json.get("bairro", ""),
                fato_end.valor_json.get("cidade", ""),
            ]
            end_val = ", ".join(p for p in partes if p) or "registrado"
        else:
            end_val = "registrado"
        alertas.append(f"endereco_entrega ja registrado como '{end_val}' — NAO peca o endereco de novo")

    # Alerta critico: municipio ambiguo — bairro existe em 2+ cidades
    if ChaveContexto.MUNICIPIO_AMBIGUO in chaves_ativas:
        fato_ambiguo = next((f for f in fatos_db if f.chave == ChaveContexto.MUNICIPIO_AMBIGUO), None)
        if fato_ambiguo:
            municipios_possiveis = fato_ambiguo.valor_texto or ""
            termo = ""
            if fato_ambiguo.valor_json and isinstance(fato_ambiguo.valor_json, dict):
                termo = fato_ambiguo.valor_json.get("termo", "")
            alertas.append(
                f"MUNICIPIO AMBIGUO: o bairro '{termo}' existe em mais de um municipio: {municipios_possiveis}. "
                "Voce DEVE perguntar ao cliente em qual cidade/municipio ele mora para calcular o frete corretamente."
            )

    # Alerta critico: erro ao tentar criar pedido (estoque zero, validacao, etc)
    if ChaveContexto.ERRO_PROMOCAO in chaves_ativas:
        fato_erro = next((f for f in fatos_db if f.chave == ChaveContexto.ERRO_PROMOCAO), None)
        if fato_erro:
            alertas.append(
                f"ERRO AO CRIAR PEDIDO: {fato_erro.valor_texto}. "
                "NAO peca confirmacao de novo. Informe o cliente sobre o problema "
                "e sugira alternativas (outro pneu, aguardar reposicao, etc)."
            )

    # Alerta critico: pedido ja criado nesta sessao
    if pedido_sessao_ctx:
        alertas.append(
            f"PEDIDO #{pedido_sessao_ctx.numero_pedido} JA FOI CRIADO NESTA SESSAO — "
            "NAO peca confirmacao de novo, NAO diga 'fechando pedido', NAO emita converter_em_pedido. "
            "O pedido esta confirmado. Responda perguntas do cliente sobre o pedido ja existente "
            "ou registre alteracoes se solicitado."
        )

    return ContextoExecutavel(
        sessao=sessao_ctx,
        cliente=cliente_ctx,
        bloqueios_ativos=bloqueios,
        mensagens_recentes=mensagens_recentes,
        fatos_ativos=fatos_ativos,
        resultados_busca_atuais=[],
        itens_provisorios=itens_provisorios,
        pendencias=pendencias,
        acoes_permitidas=acoes,
        resumo_operacional=resumo,
        frete=frete_ctx,
        tabela_fretes=tabela_fretes,
        config_loja=config_loja,
        alertas=alertas,
        pedido_sessao_atual=pedido_sessao_ctx,
        metadados=Metadados(
            gerado_em=datetime.now(timezone.utc),
            versao_contexto="v1",
        ),
    )
