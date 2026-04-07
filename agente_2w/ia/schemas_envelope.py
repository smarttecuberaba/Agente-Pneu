"""JSON Schema estrito para Structured Outputs do EnvelopeIA.

Garante que o modelo nunca devolva tipos errados (ex.: string em
bloqueios_identificados). Todos os campos ficam em "required" — opcionais
usam ["type", "null"] para compatibilidade com strict mode do OpenAI.
"""


ENVELOPE_IA_SCHEMA = {
    "type": "object",
    "properties": {
        "mensagem_cliente": {"type": "string"},
        "etapa_atual": {
            "type": "string",
            "enum": [
                "identificacao", "busca", "oferta", "confirmacao_item",
                "entrega_pagamento", "fechamento",
            ],
        },
        "intencao_atual": {"type": "string"},
        "acoes_sugeridas": {"type": "array", "items": {"type": "string"}},
        "pendencias":      {"type": "array", "items": {"type": "string"}},
        "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
        "fatos_observados": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chave":           {"type": "string"},
                    "valor":           {"type": "string"},
                    "mensagem_chat_id": {"type": ["string", "null"]},
                },
                "required": ["chave", "valor", "mensagem_chat_id"],
                "additionalProperties": False,
            },
        },
        "fatos_inferidos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chave":        {"type": "string"},
                    "valor":        {"type": "string"},
                    "justificativa": {"type": "string"},
                },
                "required": ["chave", "valor", "justificativa"],
                "additionalProperties": False,
            },
        },
        "mudancas_contexto": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chave":     {"type": "string"},
                    "valor_novo": {"type": "string"},
                    "motivo":    {"type": "string"},
                },
                "required": ["chave", "valor_novo", "motivo"],
                "additionalProperties": False,
            },
        },
        "mudancas_itens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_provisorio_id": {"type": ["string", "null"]},
                    "acao":              {"type": "string"},
                    "dados": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "status_item":    {"type": ["string", "null"]},
                                    "pneu_id":        {"type": ["string", "null"]},
                                    "quantidade":     {"type": ["integer", "null"]},
                                    "preco_unitario": {"type": ["number", "null"]},
                                    "posicao":        {"type": ["string", "null"]},
                                    "observacao":     {"type": ["string", "null"]},
                                },
                                "required": [
                                    "status_item", "pneu_id", "quantidade",
                                    "preco_unitario", "posicao", "observacao",
                                ],
                                "additionalProperties": False,
                            },
                            {"type": "null"},
                        ]
                    },
                },
                "required": ["item_provisorio_id", "acao", "dados"],
                "additionalProperties": False,
            },
        },
        "bloqueios_identificados": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "codigo_motivo":    {"type": "string"},
                    "mensagem_motivo":  {"type": "string"},
                    "campo_relacionado": {"type": ["string", "null"]},
                },
                "required": ["codigo_motivo", "mensagem_motivo", "campo_relacionado"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "mensagem_cliente", "etapa_atual", "intencao_atual",
        "acoes_sugeridas", "pendencias", "confianca",
        "fatos_observados", "fatos_inferidos", "mudancas_contexto",
        "mudancas_itens", "bloqueios_identificados",
    ],
    "additionalProperties": False,
}
