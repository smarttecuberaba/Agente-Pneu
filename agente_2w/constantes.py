"""Constantes centrais do agente — elimina strings magicas espalhadas pelo codigo."""


# Chaves usadas no contexto_conversa (campo 'chave')
class ChaveContexto:
    # ─── Moto / medida / posicao (busca de pneu) ──────────────────────────────
    MOTO_MARCA = "moto_marca"
    MOTO_MODELO = "moto_modelo"
    MOTO_ANO = "moto_ano"
    MEDIDA_INFORMADA = "medida_informada"
    POSICAO_PNEU = "posicao_pneu"

    # ─── Cliente ──────────────────────────────────────────────────────────────
    NOME_CLIENTE = "nome_cliente"
    TELEFONE_CLIENTE = "telefone_cliente"

    # ─── Entrega / pagamento ──────────────────────────────────────────────────
    TIPO_ENTREGA = "tipo_entrega"
    FORMA_PAGAMENTO = "forma_pagamento"
    ENDERECO_ENTREGA = "endereco_entrega"

    # ─── Localidade / frete ───────────────────────────────────────────────────
    MUNICIPIO = "municipio"
    MUNICIPIO_ENTREGA = "municipio_entrega"  # alias que a IA as vezes usa
    BAIRRO = "bairro"
    FRETE_VALOR = "frete_valor"
    FRETE_NAO_COBERTO = "frete_nao_coberto"
    MUNICIPIO_AMBIGUO = "municipio_ambiguo"  # localidade existe em 2+ municípios cobertos

    # ─── Flags de fluxo / estado da busca ─────────────────────────────────────
    ULTIMOS_PNEUS_ENCONTRADOS = "ultimos_pneus_encontrados"
    SEM_PREFERENCIA_MARCA = "sem_preferencia_marca"
    CLIENTE_RECUSOU_OPCAO_ATUAL = "cliente_recusou_opcao_atual"
    ITENS_FINALIZADOS = "itens_finalizados"
    PEDIDO_CANCELAMENTO_SOLICITADO = "pedido_cancelamento_solicitado"
    ERRO_PROMOCAO = "erro_promocao"  # erros de pre-condicao ao tentar criar pedido
