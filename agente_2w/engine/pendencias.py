from agente_2w.enums.enums import EtapaFluxo
from agente_2w.constantes import ChaveContexto

ACOES_POR_ETAPA: dict[EtapaFluxo, list[str]] = {
    EtapaFluxo.identificacao: [
        "pedir_clarificacao_moto",
        "pedir_clarificacao_medida",
        "pedir_clarificacao_posicao",
        "buscar_por_moto",
        "buscar_por_medida",
        "registrar_fato_observado",
        "registrar_opcoes_encontradas",
        "responder_incerteza_segura",
    ],
    EtapaFluxo.busca: [
        "buscar_por_moto",
        "buscar_por_medida",
        "buscar_medida_proxima",
        "pedir_clarificacao_moto",
        "pedir_clarificacao_medida",
        "registrar_opcoes_encontradas",
        "responder_incerteza_segura",
    ],
    EtapaFluxo.oferta: [
        "apresentar_opcoes",
        "explicar_falta",
        "pedir_escolha_cliente",
        "responder_incerteza_segura",
    ],
    EtapaFluxo.confirmacao_item: [
        "confirmar_item",
        "registrar_quantidade",
        "registrar_posicao",
        "rejeitar_item",
        "adicionar_outro_item",  # cliente quer mais pneus — volta para busca
        "finalizar_itens",       # cliente nao quer mais itens — avanca para entrega_pagamento
        "responder_incerteza_segura",
    ],
    EtapaFluxo.entrega_pagamento: [
        "perguntar_tipo_entrega",
        "perguntar_endereco",
        "perguntar_forma_pagamento",
        "registrar_entrega",
        "registrar_pagamento",
        "adicionar_outro_item",  # cliente lembrou de outro pneu — volta para busca
        "responder_incerteza_segura",
    ],
    EtapaFluxo.fechamento: [
        "revisar_pedido",
        "converter_em_pedido",
        "cancelar_pedido",
        "buscar_por_moto",           # erro_promocao (estoque=0): buscar alternativa
        "buscar_por_medida",         # erro_promocao (estoque=0): buscar por medida
        "explicar_falta",            # informar indisponibilidade
        "rejeitar_item",             # descartar item sem estoque
        "responder_incerteza_segura",
    ],
}


def acoes_permitidas(etapa: EtapaFluxo) -> list[str]:
    return ACOES_POR_ETAPA.get(etapa, ["responder_incerteza_segura"])


PENDENCIAS_POR_ETAPA: dict[EtapaFluxo, list[dict]] = {
    EtapaFluxo.identificacao: [
        {
            "codigo": "moto_ou_medida",
            "descricao": "cliente precisa informar moto ou medida do pneu",
            "campo_relacionado": ChaveContexto.MOTO_MODELO,
            "obrigatoria_para": "busca",
        },
    ],
    EtapaFluxo.busca: [
        {
            "codigo": "resultado_busca",
            "descricao": "busca precisa retornar pelo menos uma opcao real",
            "campo_relacionado": ChaveContexto.ULTIMOS_PNEUS_ENCONTRADOS,
            "obrigatoria_para": "oferta",
        },
    ],
    EtapaFluxo.oferta: [
        {
            "codigo": "escolha_cliente",
            "descricao": "cliente precisa escolher um pneu",
            "campo_relacionado": ChaveContexto.ULTIMOS_PNEUS_ENCONTRADOS,
            "obrigatoria_para": "confirmacao_item",
        },
    ],
    EtapaFluxo.confirmacao_item: [
        {
            "codigo": "item_validado",
            "descricao": "pelo menos um item provisorio confirmado com pneu_id",
            "campo_relacionado": ChaveContexto.ITENS_FINALIZADOS,
            "obrigatoria_para": "entrega_pagamento",
        },
    ],
    EtapaFluxo.entrega_pagamento: [
        {
            "codigo": ChaveContexto.TIPO_ENTREGA,
            "descricao": "tipo de entrega precisa estar definido",
            "campo_relacionado": ChaveContexto.TIPO_ENTREGA,
            "obrigatoria_para": "fechamento",
        },
        {
            "codigo": ChaveContexto.FORMA_PAGAMENTO,
            "descricao": "forma de pagamento precisa estar definida",
            "campo_relacionado": ChaveContexto.FORMA_PAGAMENTO,
            "obrigatoria_para": "fechamento",
        },
    ],
    EtapaFluxo.fechamento: [
        {
            "codigo": "pedido_pronto",
            "descricao": "todos os requisitos precisam estar validados para criar pedido",
            "campo_relacionado": "pedido",
            "obrigatoria_para": "fechamento",
        },
    ],
}


def pendencias_da_etapa(etapa: EtapaFluxo) -> list[dict]:
    return PENDENCIAS_POR_ETAPA.get(etapa, [])
