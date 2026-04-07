"""Tools de busca no catálogo — chamadas pela IA via function calling."""

import logging
import re
import unicodedata
from uuid import UUID

from agente_2w.db import catalogo_repo
from agente_2w.db import compatibilidade_web_cache_repo
from agente_2w.db import foto_pneu_repo
from agente_2w.db import log_demanda_pneu_repo

logger = logging.getLogger(__name__)

# Fabricantes conhecidos removidos antes da busca.
# Não precisa atualizar quando novas motos forem cadastradas.
_FABRICANTES = {
    "honda", "yamaha", "kawasaki", "suzuki", "triumph",
    "bmw", "harley", "davidson", "royal", "enfield",
    "ducati", "ktm", "benelli", "dafra", "shineray",
}


def _remover_acentos(texto: str) -> str:
    """Converte caracteres acentuados para equivalente ASCII.

    Ex: 'ténéré' → 'tenere', 'Lágar' → 'Lagar'
    """
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _normalizar_termo_moto(termo: str) -> list[str]:
    """Gera variações normalizadas do termo para busca robusta.

    Regras aplicadas (universais — funcionam para qualquer moto):
    1. Remove fabricante do início: "honda cb300" → "cb300"
    2. Substitui hífen/ponto por espaço: "cb-300" → "cb 300"
    3. Adiciona espaço entre letra e número: "cb300" → "cb 300"
    4. Remove acentos: "ténéré" → "tenere"

    Retorna lista de termos em ordem de prioridade.
    O caller tenta cada um até obter resultado.
    """
    termos_tentados: list[str] = []

    def _adicionar(t: str) -> None:
        t = t.strip()
        if t and t not in termos_tentados:
            termos_tentados.append(t)

    # Termo original sempre primeiro
    _adicionar(termo)

    base = termo.strip().lower()

    # Regra 4: remove acentos
    sem_acento = _remover_acentos(base)

    # Regra 1: remove fabricante do início
    palavras = sem_acento.split()
    sem_fabricante = " ".join(p for p in palavras if p not in _FABRICANTES).strip()
    if not sem_fabricante:
        sem_fabricante = sem_acento  # proteção: não esvaziar o termo

    # Regra 2: substitui hífen e ponto por espaço
    sem_separador = re.sub(r"[-.]", " ", sem_fabricante)
    sem_separador = re.sub(r"\s+", " ", sem_separador).strip()

    # Regra 3: adiciona espaço entre letra e número
    com_espaco = re.sub(r"([a-z])(\d)", r"\1 \2", sem_separador)
    com_espaco = re.sub(r"\s+", " ", com_espaco).strip()

    # Gera variações em ordem de especificidade
    _adicionar(com_espaco)           # mais normalizado: "cb 300"
    _adicionar(sem_separador)        # sem hífen/ponto: "cb300" (já sem separador)
    _adicionar(sem_fabricante)       # sem fabricante: "cb300" original sem honda/yamaha
    _adicionar(sem_acento)           # só sem acento
    _adicionar(base)                 # lowercase puro

    return termos_tentados


def buscar_pneus(
    largura: int | None = None,
    perfil: int | None = None,
    aro: int | None = None,
    medida_texto: str | None = None,
    marca_modelo: str | None = None,
) -> dict:
    """Busca pneus no catálogo por dimensões, texto de medida ou marca/modelo.

    Parâmetros (todos opcionais, mas pelo menos um deve ser informado):
        largura: largura em mm (ex: 100, 110, 120)
        perfil: altura do perfil (ex: 80, 90)
        aro: diâmetro do aro em polegadas (ex: 17, 18)
        medida_texto: trecho da medida (ex: "100/80", "110/80-18")
        marca_modelo: nome da marca ou modelo (ex: "Pirelli", "Pilot Street")

    Retorna dict com lista de pneus encontrados e quantidade.
    """
    resultados: list[dict] = []

    if marca_modelo:
        resultados = catalogo_repo.buscar_pneus_por_marca_modelo(marca_modelo)
    elif medida_texto:
        resultados = catalogo_repo.buscar_pneus_por_medida_texto(medida_texto)
    else:
        resultados = catalogo_repo.buscar_pneus_por_dimensoes(
            largura=largura, perfil=perfil, aro=aro,
        )

    return {
        "quantidade": len(resultados),
        "pneus": resultados,
    }


def _extrair_marca(texto: str) -> str | None:
    """Extrai fabricante de moto de um texto (ex: 'Yamaha Xmax 250' → 'Yamaha')."""
    for palavra in texto.lower().split():
        if palavra in _FABRICANTES:
            return palavra.capitalize()
    return None


def _extrair_ano(texto: str) -> int | None:
    """Extrai ano de moto de um texto (ex: 'Xmax 250 2024' → 2024)."""
    matches = re.findall(r'\b(20[0-2]\d)\b', texto)
    return int(matches[-1]) if matches else None


def _parsear_medida(medida: str) -> dict | None:
    """Converte string de medida em dict com largura, perfil, aro.

    Suporta todos os formatos de moto:
      '100/80-18'   → {'largura': 100, 'perfil': 80, 'aro': 18}
      '100/80 ZR18' → {'largura': 100, 'perfil': 80, 'aro': 18}
      '180/65B16'   → {'largura': 180, 'perfil': 65, 'aro': 16}  (Harley bias)
      '130/90-B16'  → {'largura': 130, 'perfil': 90, 'aro': 16}
    Rejeita dimensões absurdas (aro fora de 10-21) para não cachear lixo.
    """
    m = re.match(r'(\d{2,3})/(\d{2,3})(?:[\s\-]+[A-Z]{0,2}\s*|[A-Z]{1,2})(\d{2})', medida, re.IGNORECASE)
    if m:
        largura, perfil, aro = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (10 <= aro <= 21):
            return None
        return {"largura": largura, "perfil": perfil, "aro": aro}
    return None


def _buscar_catalogo_por_medidas(medidas_web: list[dict]) -> list[dict]:
    """Busca no catálogo pneus que correspondam às medidas descobertas via web.

    Retorna lista de pneus com estoque > 0, enriquecidos com a medida de origem.
    """
    resultados = []
    medidas_ja_buscadas = set()
    for m in medidas_web:
        chave = (m.get("largura"), m.get("perfil"), m.get("aro"))
        if chave in medidas_ja_buscadas:
            continue
        medidas_ja_buscadas.add(chave)

        pneus = catalogo_repo.buscar_pneus_por_dimensoes(
            largura=m.get("largura"),
            perfil=m.get("perfil"),
            aro=m.get("aro"),
        )
        for p in pneus:
            p["origem_medida"] = f"{chave[0]}/{chave[1]}-{chave[2]}"
            p["medida_alternativa"] = True
        resultados.extend(pneus)
    return resultados


def buscar_pneus_por_moto(
    termo_moto: str,
    posicao: str | None = None,
    sessao_id: UUID | None = None,
) -> dict:
    """Busca pneus compatíveis com uma moto pelo nome/modelo.

    Aplica normalização automática antes de buscar:
    remove fabricante, substitui hífen/ponto, adiciona espaço entre letra e
    número, remove acentos. Tenta múltiplas variações até encontrar resultado.

    Se a moto é encontrada mas todos os pneus compatíveis estão sem estoque,
    busca automaticamente medidas alternativas (cache → web) para tentar
    encontrar um pneu substituto no catálogo.

    Parâmetros:
        termo_moto: nome ou modelo da moto (ex: "CG 160", "cb300", "honda xre300")
        posicao: filtra por posição — "dianteiro", "traseiro" ou None para ambos
        sessao_id: UUID da sessão (para log de auditoria do web search)

    Retorna dict com pneus compatíveis agrupados por moto encontrada.
    """
    termos = _normalizar_termo_moto(termo_moto)
    sem_estoque_info = None  # guardado para anexar ao resultado do fallback

    for termo in termos:
        compatibilidades = catalogo_repo.buscar_compatibilidade_por_moto_texto(termo)
        if compatibilidades:
            if posicao:
                filtradas = [
                    c for c in compatibilidades
                    if c.get("posicao", "").lower() == posicao.lower()
                ]
                # Se filtro por posicao deu vazio, retorna TODAS as compatibilidades
                # para que a IA possa informar quais posicoes estao disponiveis
                if not filtradas:
                    # Log de demanda — posição indisponível
                    _ref = compatibilidades[0]
                    log_demanda_pneu_repo.registrar_busca(
                        moto=termo_moto,
                        posicao=posicao,
                        tinha_estoque=False,
                        fonte_resolucao="catalogo",
                        largura=_ref.get("largura"),
                        perfil=_ref.get("perfil"),
                        aro=_ref.get("aro"),
                        marca_moto=_ref.get("moto_marca") or _extrair_marca(termo_moto),
                        sessao_id=sessao_id,
                    )
                    return {
                        "quantidade": len(compatibilidades),
                        "compatibilidades": compatibilidades,
                        "termo_usado": termo,
                        "posicao_solicitada": posicao,
                        "aviso": f"Nenhum pneu encontrado para posicao '{posicao}'. Mostrando todas as posicoes disponiveis.",
                    }
                compatibilidades = filtradas

            # Separar pneus em estoque dos sem estoque
            com_estoque = [c for c in compatibilidades if c.get("em_estoque", True)]
            sem_estoque = [c for c in compatibilidades if not c.get("em_estoque", True)]

            if com_estoque:
                resultado = {
                    "quantidade": len(com_estoque),
                    "compatibilidades": com_estoque,
                    "termo_usado": termo,
                }
                if sem_estoque:
                    resultado["sem_estoque"] = [
                        {"pneu_id": c.get("pneu_id"), "pneu_nome": c.get("pneu_nome", ""), "medida": c.get("medida", "")}
                        for c in sem_estoque
                    ]
                    resultado["aviso_estoque"] = f"{len(sem_estoque)} pneu(s) compativel(is) sem estoque no momento."
                # Log de demanda — catálogo local
                _primeiro = com_estoque[0]
                log_demanda_pneu_repo.registrar_busca(
                    moto=termo_moto,
                    posicao=posicao or _primeiro.get("posicao", ""),
                    tinha_estoque=True,
                    fonte_resolucao="catalogo",
                    largura=_primeiro.get("largura"),
                    perfil=_primeiro.get("perfil"),
                    aro=_primeiro.get("aro"),
                    marca_moto=_primeiro.get("moto_marca") or _extrair_marca(termo_moto),
                    ano_moto=_extrair_ano(termo_moto),
                    sessao_id=sessao_id,
                    preco_encontrado=_primeiro.get("preco_venda"),
                )
                return resultado

            # Tudo sem estoque → guardar info e cair no fallback web
            sem_estoque_info = [
                {"pneu_id": c.get("pneu_id"), "pneu_nome": c.get("pneu_nome", ""), "medida": c.get("medida", "")}
                for c in sem_estoque
            ]
            logger.info(
                "Moto '%s' encontrada mas %d pneu(s) sem estoque — tentando fallback web",
                termo, len(sem_estoque),
            )
            break  # não tentar mais variações, ir direto pro fallback

    # --- Fallback: camada 2 (cache web) e camada 3 (web search) ---
    logger.info("Fallback web para '%s' posicao=%s", termo_moto, posicao)

    def _anexar_sem_estoque(resultado: dict) -> dict:
        """Anexa info de pneus sem estoque ao resultado, se houver."""
        if sem_estoque_info:
            resultado["sem_estoque"] = sem_estoque_info
            resultado["aviso_estoque"] = f"{len(sem_estoque_info)} pneu(s) compativel(is) sem estoque no momento."
        return resultado

    # Camada 2: cache
    cache = compatibilidade_web_cache_repo.buscar(termo_moto, posicao)
    if cache:
        medidas_cache = [
            {"largura": c["largura"], "perfil": c["perfil"], "aro": c["aro"]}
            for c in cache if c.get("largura") and c.get("perfil") and c.get("aro")
        ]
        pneus_alt = _buscar_catalogo_por_medidas(medidas_cache)
        _m = medidas_cache[0] if medidas_cache else {}
        if pneus_alt:
            # Log de demanda — cache web, com estoque
            log_demanda_pneu_repo.registrar_busca(
                moto=termo_moto,
                posicao=posicao or "",
                tinha_estoque=True,
                fonte_resolucao="cache",
                largura=_m.get("largura"),
                perfil=_m.get("perfil"),
                aro=_m.get("aro"),
                marca_moto=_extrair_marca(termo_moto),
                ano_moto=_extrair_ano(termo_moto),
                sessao_id=sessao_id,
                preco_encontrado=pneus_alt[0].get("preco_venda"),
            )
            return _anexar_sem_estoque({
                "quantidade": len(pneus_alt),
                "pneus": pneus_alt,
                "termo_usado": termo_moto,
                "fonte": "cache_web",
                "aviso": "Pneus encontrados via medidas alternativas (cache).",
            })
        # Cache sem estoque: NÃO loga aqui, cai pro web search ou final
        # que farão o log no ponto terminal (evita duplicata)

    # Camada 3: web search → salvar no cache → buscar no catálogo
    try:
        from agente_2w.tools.busca_web import buscar_medida_por_moto_web

        pos_web = posicao or "ambos"
        resultado_web = buscar_medida_por_moto_web(termo_moto, pos_web, sessao_id=sessao_id)

        if resultado_web.get("encontrado") and resultado_web.get("medidas_compativeis"):
            medidas_para_cache = []
            for medida_str in resultado_web["medidas_compativeis"]:
                parsed = _parsear_medida(medida_str)
                if parsed:
                    parsed["posicao"] = posicao or pos_web
                    medidas_para_cache.append(parsed)

            # Salva no cache para próximas consultas
            if medidas_para_cache:
                info_web = resultado_web.get("info", "")
                moto_nome_web = resultado_web.get("moto", termo_moto)
                texto_completo = f"{moto_nome_web} {info_web}"
                compatibilidade_web_cache_repo.salvar_lista(
                    termo_original=termo_moto,
                    moto_nome=moto_nome_web,
                    medidas=medidas_para_cache,
                    origem="web",
                    marca_moto=_extrair_marca(texto_completo),
                    ano_moto=_extrair_ano(texto_completo),
                )

            # Busca no catálogo com as medidas descobertas
            pneus_alt = _buscar_catalogo_por_medidas(medidas_para_cache)
            _m_web = medidas_para_cache[0] if medidas_para_cache else {}
            _marca_web = _extrair_marca(resultado_web.get("moto", termo_moto) + " " + resultado_web.get("info", ""))
            _ano_web = _extrair_ano(resultado_web.get("moto", termo_moto) + " " + resultado_web.get("info", ""))
            if pneus_alt:
                # Log de demanda — busca web com estoque
                log_demanda_pneu_repo.registrar_busca(
                    moto=termo_moto,
                    posicao=posicao or "",
                    tinha_estoque=True,
                    fonte_resolucao="web",
                    largura=_m_web.get("largura"),
                    perfil=_m_web.get("perfil"),
                    aro=_m_web.get("aro"),
                    marca_moto=_marca_web,
                    ano_moto=_ano_web,
                    sessao_id=sessao_id,
                    preco_encontrado=pneus_alt[0].get("preco_venda"),
                )
                return _anexar_sem_estoque({
                    "quantidade": len(pneus_alt),
                    "pneus": pneus_alt,
                    "termo_usado": termo_moto,
                    "fonte": "web_search",
                    "medidas_web": resultado_web["medidas_compativeis"],
                    "aviso": "Pneus encontrados via medidas alternativas da internet.",
                })

            # Web achou medidas mas não tem no catálogo
            # Log de demanda — busca web sem estoque
            log_demanda_pneu_repo.registrar_busca(
                moto=termo_moto,
                posicao=posicao or "",
                tinha_estoque=False,
                fonte_resolucao="web",
                largura=_m_web.get("largura"),
                perfil=_m_web.get("perfil"),
                aro=_m_web.get("aro"),
                marca_moto=_marca_web,
                ano_moto=_ano_web,
                sessao_id=sessao_id,
            )
            return _anexar_sem_estoque({
                "quantidade": 0,
                "compatibilidades": [],
                "termo_usado": termo_moto,
                "fonte": "web_search",
                "medidas_web": resultado_web["medidas_compativeis"],
                "aviso": "Medidas alternativas encontradas na internet, mas nenhuma disponível em estoque.",
            })
    except Exception:
        logger.exception("Erro no fallback web para '%s'", termo_moto)

    # Log de demanda — nada encontrado em nenhuma camada
    log_demanda_pneu_repo.registrar_busca(
        moto=termo_moto,
        posicao=posicao or "",
        tinha_estoque=False,
        fonte_resolucao="nenhuma",
        marca_moto=_extrair_marca(termo_moto),
        ano_moto=_extrair_ano(termo_moto),
        sessao_id=sessao_id,
    )
    return _anexar_sem_estoque({
        "quantidade": 0,
        "compatibilidades": [],
        "termo_usado": termo_moto,
    })


def buscar_detalhes_pneu(pneu_id: str) -> dict:
    """Busca detalhes completos de um pneu específico pelo ID.

    Parâmetros:
        pneu_id: UUID do pneu

    Retorna dict com dados do pneu ou mensagem de não encontrado.
    """
    pneu = catalogo_repo.buscar_pneu_por_id(UUID(pneu_id))
    if pneu is None:
        return {"encontrado": False, "mensagem": "Pneu não encontrado."}

    estoque = catalogo_repo.buscar_estoque_por_pneu(UUID(pneu_id))

    fotos = foto_pneu_repo.listar_fotos(UUID(pneu_id))

    return {
        "encontrado": True,
        "pneu": pneu.model_dump(mode="json"),
        "estoque": estoque.model_dump(mode="json") if estoque else None,
        "fotos": fotos,
    }
