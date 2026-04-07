"""Tool de busca de medidas de pneu via Web Search (Responses API).

Usado como fallback quando buscar_pneus_por_moto nao encontra a moto
no catalogo proprio. Busca a medida na internet e devolve ao agente
uma lista de medidas compativeis (medida original + variacoes aceitas),
para que ele tente cada uma no catalogo antes de desistir.
"""

import logging
import re
from uuid import UUID

from openai import OpenAI

from agente_2w.config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

_client = OpenAI(api_key=OPENAI_API_KEY)


def _extrair_medidas(texto: str) -> list[str]:
    """Extrai todas as medidas de pneu mencionadas em um texto livre.

    Reconhece formatos:
      - 190/50-17, 190/50 ZR17, 190/50ZR17  (moto esportiva/naked)
      - 90/90-18, 100/90-18, 80/100-18       (moto urbana)
      - 180/65B16, 130/90-B16               (Harley bias-ply)
      - MH90-21, MT90-16                    (Harley métrico americano)
      - 2.75-18, 3.00-17                    (medida antiga)
    """
    # Padrão moderno universal: aceita qualquer letra como separador (ZR, R, B, D, H...)
    # Separador obrigatório (espaço/hífen OU letra) para não casar "250/2024" (ano de modelo)
    padrao_moderno = r'\b\d{2,3}/\d{2,3}(?:[\s\-]+[A-Z]{0,2}\s*|[A-Z]{1,2})\d{2}\b'
    # Padrão métrico americano Harley: MH90-21, MT90-16
    padrao_harley = r'\b[A-Z]{2}\d{2}[\s\-]\d{2}\b'
    # Padrão antigo: 2.75-18, 3.00-17
    padrao_antigo = r'\b\d\.\d{2}[\s\-]\d{2}\b'

    matches = re.findall(padrao_moderno, texto, re.IGNORECASE)
    matches += re.findall(padrao_harley, texto, re.IGNORECASE)
    matches += re.findall(padrao_antigo, texto, re.IGNORECASE)

    # Normaliza espaços e remove duplicatas mantendo ordem
    vistas = set()
    resultado = []
    for m in matches:
        m_norm = m.strip()
        if m_norm.lower() not in vistas:
            vistas.add(m_norm.lower())
            resultado.append(m_norm)

    return resultado


def buscar_medida_por_moto_web(moto: str, posicao: str, sessao_id: UUID | None = None) -> dict:
    """Busca na internet as medidas de pneu compativeis com uma moto.

    Usar SOMENTE quando buscar_pneus_por_moto retornar 0 resultados.

    Retorna lista de medidas compativeis (medida_original + variacoes aceitas
    pelo mercado), para que o agente busque cada uma no catalogo antes de
    desistir. Isso evita perda de venda quando a loja tem uma medida alternativa
    compativel mas nao a medida exata de fabrica.

    Apos receber o resultado:
    1. Chame buscar_pneus com cada medida de `medidas_compativeis`, uma por vez.
    2. Pare na primeira que retornar resultado no catalogo.
    3. So diga ao cliente que nao tem apos tentar todas da lista.

    Parametros:
        moto: nome completo da moto (ex: "Kawasaki Z1000", "Honda CG 160 Fan")
        posicao: "traseiro", "dianteiro" ou "ambos"
    """
    query = (
        f"Quais medidas de pneu {posicao} são compatíveis com {moto}? "
        f"Liste a medida original de fábrica e todas as medidas alternativas "
        f"aceitas pelo mercado de reposição, com os tamanhos no formato padrão "
        f"(ex: 190/50-17, 190/55-17)."
    )

    try:
        response = _client.responses.create(
            model=OPENAI_MODEL,
            input=query,
            tools=[{
                "type": "web_search_preview",
                "search_context_size": "low",
                "user_location": {
                    "type": "approximate",
                    "country": "BR",
                    "timezone": "America/Sao_Paulo",
                },
            }],
        )

        info = response.output_text or ""
        medidas = _extrair_medidas(info)
        encontrado = bool(medidas)

        logger.info(
            "Web search medidas '%s' (%s): %s | medidas=%s",
            moto, posicao, info[:120], medidas,
        )

        return {
            "encontrado": encontrado,
            "moto": moto,
            "posicao": posicao,
            "medidas_compativeis": medidas,          # lista ordenada: original primeiro
            "medida_original": medidas[0] if medidas else None,
            "info": info,
            "fonte": "web",
        }

    except Exception as e:
        logger.warning("Web search falhou para '%s' (%s): %s", moto, posicao, e)
        return {
            "encontrado": False,
            "moto": moto,
            "posicao": posicao,
            "medidas_compativeis": [],
            "medida_original": None,
            "info": "",
            "fonte": "web",
            "erro": str(e),
        }
