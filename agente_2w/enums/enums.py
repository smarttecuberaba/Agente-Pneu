from enum import Enum


class TipoDeVerdade(str, Enum):
    observado = "observado"
    inferido = "inferido"
    validado_tool = "validado_tool"
    confirmado_cliente = "confirmado_cliente"
    validado_backend = "validado_backend"
    oficializado = "oficializado"


class EtapaFluxo(str, Enum):
    identificacao = "identificacao"
    busca = "busca"
    oferta = "oferta"
    confirmacao_item = "confirmacao_item"
    entrega_pagamento = "entrega_pagamento"
    fechamento = "fechamento"


class StatusSessao(str, Enum):
    ativa = "ativa"
    aguardando_cliente = "aguardando_cliente"
    bloqueada = "bloqueada"
    fechada = "fechada"


class NivelConfirmacao(str, Enum):
    nenhum = "nenhum"
    confirmado_cliente = "confirmado_cliente"
    validado_tool = "validado_tool"
    validado_backend = "validado_backend"
    oficializado = "oficializado"


class OrigemContexto(str, Enum):
    mensagem_cliente = "mensagem_cliente"
    inferido_ia = "inferido_ia"
    tool = "tool"
    backend = "backend"
    operador = "operador"
    sistema = "sistema"


class StatusItemProvisorio(str, Enum):
    sugerido = "sugerido"
    selecionado_cliente = "selecionado_cliente"
    validado = "validado"
    rejeitado = "rejeitado"
    cancelado = "cancelado"
    promovido = "promovido"


class TipoEntrega(str, Enum):
    retirada = "retirada"
    entrega = "entrega"
    a_confirmar = "a_confirmar"


class FormaPagamento(str, Enum):
    pix = "pix"
    dinheiro = "dinheiro"
    cartao = "cartao"
    transferencia = "transferencia"
    a_confirmar = "a_confirmar"


class StatusPedido(str, Enum):
    confirmado = "confirmado"
    cancelado = "cancelado"
    entregue = "entregue"


class Confianca(str, Enum):
    alta = "alta"
    media = "media"
    baixa = "baixa"


class Direcao(str, Enum):
    entrada = "entrada"
    saida = "saida"


class Remetente(str, Enum):
    cliente = "cliente"
    agente = "agente"
    operador = "operador"


class Posicao(str, Enum):
    dianteiro = "dianteiro"
    traseiro = "traseiro"
    par = "par"
