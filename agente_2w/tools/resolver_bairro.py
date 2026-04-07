"""Resolução de bairro→município via cache + web_search.

Recebe um termo livre digitado pelo cliente (ex: "bangu", "sanTisimo",
"sto cristo") e devolve o município oficial do RJ que cobre aquele bairro.

Fluxo:
  1. Normaliza o termo
  2. Consulta cache (bairro_municipio_cache)
  3. Se cache miss → web_search (OpenAI Responses API)
  4. Valida se o município retornado está na lista coberta
  5. Salva resultado no cache (inclusive "não cobre", para evitar re-consulta)
  6. Retorna (bairro_oficial, municipio) ou (None, None)
"""
import json
import logging
import re
import time
import unicodedata
from uuid import UUID

from openai import OpenAI

from agente_2w.config import OPENAI_API_KEY, OPENAI_MODEL
from agente_2w.db import area_entrega_repo, bairro_municipio_cache_repo

logger = logging.getLogger(__name__)

_client = OpenAI(api_key=OPENAI_API_KEY)

# ---------------------------------------------------------------------------
# Municípios cobertos — carregados do banco com TTL de 1 hora
# ---------------------------------------------------------------------------

# Fallback de emergência caso o banco esteja indisponível
_FALLBACK_MUNICIPIOS = {
    "rio de janeiro": "Rio de Janeiro",
    "niteroi": "Niterói",
    "sao goncalo": "São Gonçalo",
    "duque de caxias": "Duque de Caxias",
    "nova iguacu": "Nova Iguaçu",
    "sao joao de meriti": "São João de Meriti",
    "belford roxo": "Belford Roxo",
    "nilopolis": "Nilópolis",
    "queimados": "Queimados",
    "mage": "Magé",
    "marica": "Maricá",
    "tangua": "Tanguá",
    "rio bonito": "Rio Bonito",
    "araruama": "Araruama",
    "saquarema": "Saquarema",
    "itaborai": "Itaboraí",
}

_TTL_SEGUNDOS = 3600  # 1 hora

_cache_municipios: tuple[set[str], dict[str, str]] | None = None
_cache_carregado_em: float = 0.0


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = sem_acento.encode("ascii", "ignore").decode("ascii")
    return sem_acento.strip().lower()


def _carregar_municipios_do_banco() -> tuple[set[str], dict[str, str]]:
    """Carrega municípios ativos de area_entrega via repo existente."""
    try:
        nomes = area_entrega_repo.listar_municipios_ativos()
        if not nomes:
            raise ValueError("Lista vazia retornada do banco")
        cobertos: set[str] = set()
        oficial: dict[str, str] = {}
        for nome in nomes:
            norm = _normalizar(nome)
            cobertos.add(norm)
            oficial[norm] = nome
        logger.info("Municípios carregados do banco: %d", len(cobertos))
        return cobertos, oficial
    except Exception:
        logger.warning(
            "Falha ao carregar municípios do banco — usando fallback hardcoded"
        )
        return set(_FALLBACK_MUNICIPIOS.keys()), dict(_FALLBACK_MUNICIPIOS)


def _obter_municipios() -> tuple[set[str], dict[str, str]]:
    """Retorna (cobertos, nome_oficial) com TTL de 1 hora."""
    global _cache_municipios, _cache_carregado_em
    agora = time.monotonic()
    if _cache_municipios is None or (agora - _cache_carregado_em) > _TTL_SEGUNDOS:
        _cache_municipios = _carregar_municipios_do_banco()
        _cache_carregado_em = agora
    return _cache_municipios


def _e_municipio_coberto(nome: str) -> str | None:
    """Retorna o nome oficial se o município estiver coberto, senão None."""
    _, nome_oficial = _obter_municipios()
    norm = _normalizar(nome)
    return nome_oficial.get(norm)


def _extrair_json_resposta(texto: str) -> dict:
    """Extrai o primeiro objeto JSON da resposta do modelo."""
    try:
        # Tenta bloco ```json ... ```
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        # Tenta JSON direto na resposta
        match = re.search(r"\{[^{}]+\}", texto, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except (json.JSONDecodeError, AttributeError):
        pass
    return {}


def _consultar_web(termo: str) -> tuple[str | None, list[str]]:
    """Chama web_search para resolver bairro→município no RJ.

    Estratégia de busca: pesquisa "{termo} bairro município Rio de Janeiro"
    — padrão que o Google resolve corretamente mesmo com nomes abreviados,
    grafias erradas ou gírias locais (ex: "calunga", "bangu", "sto cristo").

    Retorna (bairro_oficial, municipios_cobertos) onde municipios_cobertos
    é uma lista com 0, 1 ou mais municípios. Lista vazia = não encontrado.
    Lista com 2+ itens = ambíguo (localidade existe em mais de uma cidade coberta).
    """
    _, nome_oficial = _obter_municipios()
    municipios_lista = ", ".join(sorted(nome_oficial.values()))
    prompt = (
        f'Pesquise na web: "{termo} bairro município Rio de Janeiro"\n\n'
        f"Com base no resultado, responda:\n"
        f"1. Qual o nome OFICIAL desse bairro/localidade?\n"
        f"2. Em qual município ele fica?\n\n"
        f"Responda APENAS com o JSON abaixo:\n"
        f'{{"bairro": "<nome oficial do bairro>", "municipios": ["<municipio>"]}}\n\n'
        f"REGRAS:\n"
        f"- Os municípios DEVEM ser desta lista (ignore outros): {municipios_lista}\n"
        f"- Se o bairro existir em 2+ municípios da lista, inclua todos: {{\"municipios\": [\"X\", \"Y\"]}}\n"
        f"- Se não for bairro/localidade conhecida em nenhum desses municípios:\n"
        f'  {{"bairro": null, "municipios": []}}'
    )

    try:
        response = _client.responses.create(
            model=OPENAI_MODEL,
            input=prompt,
            tools=[{
                "type": "web_search_preview",
                "search_context_size": "low",
                "user_location": {
                    "type": "approximate",
                    "country": "BR",
                    "city": "Rio de Janeiro",
                    "timezone": "America/Sao_Paulo",
                },
            }],
        )

        texto = response.output_text or ""
        logger.info("web_search resolver_bairro '%s': %s", termo, texto[:200])

        dados = _extrair_json_resposta(texto)
        bairro = dados.get("bairro") or None

        # Aceita tanto "municipios" (lista, novo formato) quanto "municipio" (string, legado)
        municipios_raw: list = []
        if isinstance(dados.get("municipios"), list):
            municipios_raw = dados["municipios"]
        elif dados.get("municipio"):
            municipios_raw = [dados["municipio"]]

        # Filtra apenas os que estão na lista coberta
        cobertos: list[str] = []
        for m in municipios_raw:
            oficial = _e_municipio_coberto(str(m))
            if oficial and oficial not in cobertos:
                cobertos.append(oficial)

        return bairro, cobertos

    except Exception:
        logger.exception("Erro no web_search ao resolver bairro '%s'", termo)
        return None, []


def resolver_bairro_municipio(
    termo: str,
    sessao_id: UUID | None = None,  # reservado para log futuro
) -> tuple[str | None, str | None, list[str] | None]:
    """Resolve um termo livre para (bairro_oficial, municipio, ambiguos).

    Retorna uma 3-tupla:
    - Encontrado único:   (bairro, municipio, None)
    - Ambíguo (2+ cidades): (bairro, None, [municipio1, municipio2, ...])
    - Não encontrado:     (None, None, None)

    Exemplos:
        "bangu"          → ("Bangu", "Rio de Janeiro", None)
        "santa isabel"   → ("Santa Isabel", None, ["Magé", "São Gonçalo"])  # ambíguo
        "petrópolis"     → (None, None, None)  # fora da área
    """
    if not termo or not termo.strip():
        return None, None, None

    termo = termo.strip()

    # Atalho: se o próprio termo já é um município coberto, não precisa resolver
    municipio_direto = _e_municipio_coberto(termo)
    if municipio_direto:
        return None, municipio_direto, None

    # 1. Consulta cache (armazena apenas resultados não-ambíguos)
    cache = bairro_municipio_cache_repo.buscar(termo)
    if cache is not None:
        logger.info(
            "Cache hit para '%s': bairro=%s, municipio=%s",
            termo, cache["bairro"], cache["municipio"],
        )
        return cache["bairro"], cache["municipio"], None

    # 2. Cache miss → web_search
    logger.info("Cache miss para '%s' — chamando web_search", termo)
    bairro, municipios = _consultar_web(termo)

    if len(municipios) > 1:
        # Ambíguo: não salva no cache — o agente vai pedir que o cliente esclareça
        logger.info(
            "Localidade ambígua '%s': municípios possíveis = %s",
            termo, municipios,
        )
        return bairro, None, municipios

    municipio = municipios[0] if municipios else None

    # 3. Salva no cache (inclusive None = fora de cobertura, para evitar re-consulta)
    bairro_municipio_cache_repo.salvar(
        termo_original=termo,
        bairro=bairro,
        municipio=municipio,
        fonte="web_search",
    )

    return bairro, municipio, None
