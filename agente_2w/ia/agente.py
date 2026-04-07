"""Agente IA — chamada ao OpenAI com function calling e contexto."""

import json
import logging

from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from agente_2w.config import OPENAI_API_KEY, OPENAI_MODEL, MAX_TOOL_ROUNDS

logger = logging.getLogger(__name__)

OPENAI_TIMEOUT = 30  # segundos
from agente_2w.ia.prompt_sistema import SYSTEM_PROMPT
from agente_2w.schemas.contexto_executavel import ContextoExecutavel
from agente_2w.tools.busca_catalogo import (
    buscar_pneus,
    buscar_pneus_por_moto,
    buscar_detalhes_pneu,
)
from agente_2w.tools.consulta_estoque import consultar_estoque
from agente_2w.tools.resolve_cliente import resolver_cliente

_client = OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT)

from agente_2w.ia.schemas_envelope import ENVELOPE_IA_SCHEMA as _ENVELOPE_IA_SCHEMA
from agente_2w.ia.tools_schema import TOOLS_SCHEMA, TOOLS_COM_PNEU as _TOOLS_COM_PNEU
from agente_2w.ia.extracao_pneus import extrair_pneus_de_resultado as _extrair_pneus_de_resultado

# ---------- Mapa de dispatch das tools ----------

_TOOL_DISPATCH: dict = {
    "buscar_pneus": buscar_pneus,
    "buscar_pneus_por_moto": buscar_pneus_por_moto,
    "buscar_detalhes_pneu": buscar_detalhes_pneu,
    "consultar_estoque": consultar_estoque,
    "resolver_cliente": resolver_cliente,
}

_RETRY_EXCEPTIONS = (RateLimitError, APITimeoutError, APIConnectionError)


@retry(
    retry=retry_if_exception_type(_RETRY_EXCEPTIONS),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=lambda retry_state: logger.warning(
        "OpenAI retry %d apos %s: %s",
        retry_state.attempt_number,
        type(retry_state.outcome.exception()).__name__,
        retry_state.outcome.exception(),
    ),
    reraise=True,
)
def _chamar_openai(messages: list, tools=None) -> object:
    """Chamada OpenAI com retry automatico para rate limit e timeout."""
    kwargs = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "EnvelopeIA",
                "strict": True,
                "schema": _ENVELOPE_IA_SCHEMA,
            },
        },
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
        kwargs["parallel_tool_calls"] = False  # obrigatorio com structured outputs
    return _client.chat.completions.create(**kwargs)


def _executar_tool(nome: str, argumentos: dict, dispatch: dict | None = None) -> str:
    """Executa uma tool pelo nome e retorna o resultado serializado."""
    fn = (dispatch or _TOOL_DISPATCH).get(nome)
    if fn is None:
        return json.dumps({"erro": f"Tool '{nome}' não encontrada."})
    resultado = fn(**argumentos)
    return json.dumps(resultado, ensure_ascii=False, default=str)


def chamar_agente(
    contexto: ContextoExecutavel,
    mensagem_usuario: str,
    imagens: list[str] | None = None,
) -> tuple[str, list[dict]]:
    """Envia mensagem do usuário + contexto para o modelo e processa tool calls.

    Args:
        imagens: lista de URLs de imagens enviadas pelo cliente (opcional).
                 Quando presente, o content do usuário vira array multimodal.

    Retorna tupla:
        - texto bruto da resposta final do modelo (JSON do EnvelopeIA)
        - lista de pneus encontrados pelas tools (pneu_id, posicao, preco_venda)
    """
    contexto_json = contexto.model_dump_json(indent=None)

    # Monta content do usuário: string simples ou array multimodal (com imagens)
    if imagens:
        user_content: list[dict] | str = [{"type": "text", "text": mensagem_usuario or "(sem texto)"}]
        for url in imagens:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": url, "detail": "auto"},
            })
    else:
        user_content = mensagem_usuario

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": f"CONTEXTO ATUAL DA SESSÃO (JSON):\n{contexto_json}",
        },
        {"role": "user", "content": user_content},
    ]

    pneus_encontrados: list[dict] = []

    # Injeta sessao_id em buscar_pneus_por_moto para auditoria do web search interno
    sessao_id = contexto.sessao.sessao_id
    dispatch = {
        **_TOOL_DISPATCH,
        "buscar_pneus_por_moto": lambda termo_moto, posicao=None: buscar_pneus_por_moto(
            termo_moto=termo_moto, posicao=posicao, sessao_id=sessao_id
        ),
    }

    for round_num in range(MAX_TOOL_ROUNDS):
        response = _chamar_openai(messages, tools=TOOLS_SCHEMA)
        choice = response.choices[0]

        # Se não tem tool calls, retornar a resposta final
        if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
            return choice.message.content or "", pneus_encontrados

        # Processar cada tool call
        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            args = json.loads(tool_call.function.arguments)
            logger.debug("Tool call: %s(%s)", tool_call.function.name, args)
            resultado = _executar_tool(tool_call.function.name, args, dispatch=dispatch)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": resultado,
            })

            # Coletar pneu_ids de tools de busca
            if tool_call.function.name in _TOOLS_COM_PNEU:
                novos = _extrair_pneus_de_resultado(resultado)
                pneus_encontrados.extend(novos)

    # Se esgotou os rounds, fazer uma última chamada sem tools
    logger.warning("Esgotou %d rounds de tool calls, chamando sem tools", MAX_TOOL_ROUNDS)
    response = _chamar_openai(messages)
    return response.choices[0].message.content or "", pneus_encontrados
