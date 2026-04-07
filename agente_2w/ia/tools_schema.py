"""Schema das function-calling tools disponibilizadas a IA.

A lista TOOLS_SCHEMA descreve para o modelo cada tool (nome, descricao,
parametros JSON). O dispatcher efetivo que mapeia nome -> callable vive em
`ia/agente.py` porque depende das implementacoes reais.
"""


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "buscar_pneus",
            "description": "Busca pneus no catálogo por dimensões, texto de medida ou marca/modelo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "largura": {"type": "integer", "description": "Largura em mm (ex: 100, 110)"},
                    "perfil": {"type": "integer", "description": "Altura do perfil (ex: 80, 90)"},
                    "aro": {"type": "integer", "description": "Diâmetro do aro em polegadas (ex: 17, 18)"},
                    "medida_texto": {"type": "string", "description": "Trecho da medida (ex: '100/80', '110/80-18')"},
                    "marca_modelo": {"type": "string", "description": "Nome da marca ou modelo (ex: 'Pirelli', 'Pilot Street')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_pneus_por_moto",
            "description": "Busca pneus compatíveis com uma moto pelo nome/modelo. Filtre por posicao sempre que souber qual o cliente quer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "termo_moto": {"type": "string", "description": "Nome ou modelo da moto (ex: 'CG 160', 'Biz 125')"},
                    "posicao": {"type": "string", "enum": ["dianteiro", "traseiro"], "description": "Posição do pneu. Informe sempre que souber."},
                },
                "required": ["termo_moto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_detalhes_pneu",
            "description": "Busca detalhes completos de um pneu específico pelo UUID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pneu_id": {"type": "string", "description": "UUID do pneu"},
                },
                "required": ["pneu_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_estoque",
            "description": "Consulta disponibilidade e preço de um pneu específico pelo UUID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pneu_id": {"type": "string", "description": "UUID do pneu"},
                },
                "required": ["pneu_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolver_cliente",
            "description": "Busca um cliente pelo telefone. Se não existir, cria um novo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "telefone": {"type": "string", "description": "Telefone do cliente (ex: '11999998888')"},
                    "nome": {"type": "string", "description": "Nome do cliente (opcional)"},
                },
                "required": ["telefone"],
            },
        },
    },
]

# Nomes de tools que retornam pneu_id (para auto-enriquecimento downstream)
TOOLS_COM_PNEU = {
    "buscar_pneus",
    "buscar_pneus_por_moto",
    "buscar_detalhes_pneu",
    "consultar_estoque",
}
