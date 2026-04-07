"""
Template do prompt de retry enviado a IA quando o envelope inicial e rejeitado.

Quando o validador_envelope encontra erros, o orquestrador reenvia a mensagem
original anotada com os erros + regras obrigatorias + formato do JSON esperado.
Isolar este template facilita ajustes no texto sem mexer na logica do retry.
"""
from typing import Sequence


_TEMPLATE_RETRY = (
    "[MENSAGEM ORIGINAL DO CLIENTE]: {mensagem_original}\n\n"
    "[CORRECAO OBRIGATORIA DO BACKEND]: Sua resposta foi REJEITADA.\n"
    "Erros encontrados:\n"
    "{lista_erros}"
    "\n\nREGRAS OBRIGATORIAS:"
    "\n1. etapa_atual DEVE ser uma destas: {etapas_validas}"
    "\n2. acoes_sugeridas DEVEM conter apenas acoes desta lista: [{acoes_permitidas}]"
    "\n3. NAO transicione para etapa que nao esta na lista acima"
    "\n\nFORMATO OBRIGATORIO para este turno:"
    '\n{{"etapa_atual": "{proxima_etapa}", "acoes_sugeridas": ["{acao_exemplo}"], '
    '"mensagem_cliente": "...(sua resposta ao cliente)...", '
    '"intencao_atual": "...", "confianca": "alta", '
    '"fatos_observados": [], "fatos_inferidos": [], '
    '"mudancas_contexto": [], "mudancas_itens": [], "bloqueios_identificados": []}}'
    "\n\nRetorne APENAS o JSON corrigido, sem texto antes ou depois."
)

_ACAO_FALLBACK = "responder_incerteza_segura"


def montar_prompt_retry(
    mensagem_original: str,
    erros: Sequence[str],
    etapas_validas: Sequence[str],
    acoes_permitidas: Sequence[str],
    proxima_etapa: str,
) -> str:
    """Monta o prompt de retry a partir dos dados do turno rejeitado.

    Parametros:
      - mensagem_original: texto que o cliente enviou (enviado em anexo para contexto)
      - erros: mensagens de erro retornadas pelo validador_envelope
      - etapas_validas: etapa_atual + proximas_etapas() da maquina de estados
      - acoes_permitidas: acoes validas na etapa atual (de pendencias.acoes_permitidas)
      - proxima_etapa: etapa sugerida como exemplo no JSON do formato
    """
    lista_erros = "\n".join(f"- {e}" for e in erros)
    acao_exemplo = acoes_permitidas[0] if acoes_permitidas else _ACAO_FALLBACK
    return _TEMPLATE_RETRY.format(
        mensagem_original=mensagem_original,
        lista_erros=lista_erros,
        etapas_validas=", ".join(etapas_validas),
        acoes_permitidas=", ".join(acoes_permitidas),
        proxima_etapa=proxima_etapa,
        acao_exemplo=acao_exemplo,
    )
