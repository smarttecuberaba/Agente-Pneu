"""Extracao de localidade a partir de endereco livre + consulta de frete.

Parseia municipio/bairro do fato endereco_entrega (JSON estruturado ou
texto livre), persiste na ficha do cliente e consulta a tabela de fretes
para registrar frete_valor ou frete_nao_coberto como fatos da sessao.
"""
import logging
import re
from uuid import UUID

from agente_2w.db import contexto_repo, cliente_repo, area_entrega_repo
from agente_2w.constantes import ChaveContexto
from agente_2w.enums.enums import TipoDeVerdade, NivelConfirmacao, OrigemContexto
from agente_2w.schemas.contexto_conversa import ContextoConversaCreate

logger = logging.getLogger(__name__)


def _parsear_localidade_endereco(fato) -> tuple[str | None, str | None]:
    """Extrai (municipio, bairro) do fato endereco_entrega.

    Tenta primeiro valor_json estruturado, depois parseia valor_texto livre.
    Formato tipico: "Rua X, 123, Bairro Centro, Caxias do Sul, RS"
    """
    # Caso 1: JSON estruturado com chaves explicitas
    if fato.valor_json and isinstance(fato.valor_json, dict):
        d = fato.valor_json
        municipio = d.get("municipio") or d.get("cidade")
        bairro = d.get("bairro")
        return municipio or None, bairro or None

    # Caso 2: texto livre
    texto = fato.valor_texto
    if not texto:
        return None, None

    partes = [p.strip() for p in texto.split(",") if p.strip()]

    # Filtra partes que sao claramente logradouro/numero/cep
    # (numero puro ou CEP de 8 digitos)
    def e_numero_ou_cep(s: str) -> bool:
        return bool(re.match(r'^\d[\d\-]*$', s))

    # Sigla de estado brasileira: 2 letras maiusculas
    def e_sigla_estado(s: str) -> bool:
        return bool(re.match(r'^[A-Z]{2}$', s))

    # Bairro: parte que comeca com "Bairro " (case-insensitive)
    bairro = None
    for parte in partes:
        if parte.lower().startswith("bairro "):
            bairro = parte[7:].strip()
            break

    # Candidatos a municipio/bairro: remove numeros, siglas de estado e prefixo "Rua/Av/etc"
    _PREFIXOS_LOGRADOURO = ("rua ", "av ", "avenida ", "alameda ", "travessa ",
                             "estrada ", "rodovia ", "praca ", "largo ")
    candidatos = [
        p for p in partes
        if not e_numero_ou_cep(p)
        and not e_sigla_estado(p)
        and not any(p.lower().startswith(pref) for pref in _PREFIXOS_LOGRADOURO)
        and not p.lower().startswith("bairro ")
    ]

    # Municipio: ultimo candidato
    municipio = candidatos[-1] if candidatos else None

    # Se bairro nao encontrado por prefixo e tem pelo menos 2 candidatos,
    # o penultimo e provavelmente o bairro
    if bairro is None and len(candidatos) >= 2:
        bairro = candidatos[-2]

    return municipio or None, bairro or None


def _atualizar_localidade_cliente(sessao_id: UUID, cliente_id) -> None:
    """Persiste municipio/bairro no cliente a partir dos fatos da sessao.

    Ordem de prioridade:
    1. Fatos explicitos 'municipio'/'bairro' registrados pela IA
    2. Parse do fato 'endereco_entrega' (JSON estruturado ou texto livre)
    Nao sobrescreve se o cliente ja tem o campo preenchido.
    """
    try:
        cliente = cliente_repo.buscar_cliente_por_id(cliente_id)
        if not cliente:
            return

        campos: dict = {}

        # Prioridade 1: fatos explicitos registrados pela IA
        if not cliente.municipio:
            fato = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.MUNICIPIO)
            if fato and fato.valor_texto:
                campos["municipio"] = fato.valor_texto

        if not cliente.bairro:
            fato = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.BAIRRO)
            if fato and fato.valor_texto:
                campos["bairro"] = fato.valor_texto

        # Prioridade 2: parsear endereco_entrega se ainda faltam campos
        municipio_pendente = not cliente.municipio and "municipio" not in campos
        bairro_pendente = not cliente.bairro and "bairro" not in campos

        if municipio_pendente or bairro_pendente:
            fato_end = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.ENDERECO_ENTREGA)
            if fato_end:
                municipio_parsed, bairro_parsed = _parsear_localidade_endereco(fato_end)
                if municipio_pendente and municipio_parsed:
                    campos["municipio"] = municipio_parsed
                if bairro_pendente and bairro_parsed:
                    campos["bairro"] = bairro_parsed

        if campos:
            cliente_repo.atualizar_cliente(cliente_id, campos)
            logger.info("Localidade cliente %s atualizada: %s", cliente_id, campos)
    except Exception:
        logger.exception("Falha ao atualizar localidade do cliente")


def _consultar_e_registrar_frete(sessao_id: UUID) -> None:
    """Consulta frete para o municipio do cliente e registra como fato.

    Executa sempre que ha municipio definido, exceto quando o cliente ja
    escolheu retirada (sem frete a calcular). Isso permite responder
    perguntas como "voces entregam em X?" antes de o cliente confirmar
    a modalidade de entrega.
    Registra 'frete_valor' (com valor) ou 'frete_nao_coberto' (sem cobertura).
    Idempotente: nao reconsulta se ja existe fato de frete valido.
    """
    try:
        # Pular apenas se o cliente escolheu retirada — sem frete a calcular.
        # Executa mesmo quando tipo_entrega ainda nao foi definido (cliente perguntou
        # sobre entrega antes de confirmar a modalidade).
        fato_entrega = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.TIPO_ENTREGA)
        if fato_entrega and fato_entrega.valor_texto == "retirada":
            # Limpar frete antigo se existir (cliente mudou de entrega para retirada)
            for chave_frete in (ChaveContexto.FRETE_VALOR, ChaveContexto.FRETE_NAO_COBERTO):
                try:
                    contexto_repo.desativar_fato_anterior(sessao_id, chave_frete)
                except Exception:
                    pass
            return

        # Obter municipio atual: fato explicito > parse do endereco
        # A IA pode usar "municipio" ou "municipio_entrega" como chave
        municipio = None
        bairro = None

        for chave_mun in (ChaveContexto.MUNICIPIO, ChaveContexto.MUNICIPIO_ENTREGA):
            fato_municipio = contexto_repo.buscar_fato_ativo(sessao_id, chave_mun)
            if fato_municipio and fato_municipio.valor_texto:
                municipio = fato_municipio.valor_texto
                break

        fato_bairro = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.BAIRRO)
        if fato_bairro and fato_bairro.valor_texto:
            bairro = fato_bairro.valor_texto

        if not municipio:
            fato_end = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.ENDERECO_ENTREGA)
            if fato_end:
                municipio_parsed, bairro_parsed = _parsear_localidade_endereco(fato_end)
                municipio = municipio_parsed
                if bairro_parsed and not bairro:
                    bairro = bairro_parsed

        if not municipio:
            return

        # Se havia ambiguidade e agora temos municipio definido, limpar o fato ambiguo
        try:
            contexto_repo.desativar_fato_anterior(sessao_id, ChaveContexto.MUNICIPIO_AMBIGUO)
        except Exception:
            pass

        # Idempotencia: se frete ja foi calculado para o mesmo municipio, nao recalcula.
        # Se o municipio mudou (cliente corrigiu), desativa o frete antigo e recalcula.
        fato_frete = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.FRETE_VALOR)
        fato_nao_coberto = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.FRETE_NAO_COBERTO)
        if fato_frete or fato_nao_coberto:
            # Municipio usado no frete anterior
            municipio_anterior = None
            if fato_nao_coberto:
                municipio_anterior = fato_nao_coberto.valor_texto
            elif fato_frete:
                # frete_valor nao armazena municipio diretamente; comparar via fato municipio anterior
                # Se existe frete_valor, o municipio era coberto — se municipio nao mudou, manter
                municipio_anterior = municipio  # assume mesmo se nao conseguir determinar

                # Tentar extrair municipio do fato frete_valor via JSON ou do contexto
                if fato_frete.valor_json and isinstance(fato_frete.valor_json, dict):
                    municipio_anterior = fato_frete.valor_json.get("municipio", municipio)

            if municipio_anterior and municipio_anterior.lower() == municipio.lower():
                return  # mesmo municipio, frete ja calculado

            # Municipio mudou — limpar frete antigo antes de recalcular
            logger.info("Municipio mudou ('%s' → '%s'), recalculando frete", municipio_anterior, municipio)
            for chave_frete in (ChaveContexto.FRETE_VALOR, ChaveContexto.FRETE_NAO_COBERTO):
                try:
                    contexto_repo.desativar_fato_anterior(sessao_id, chave_frete)
                except Exception:
                    pass

        valor_frete = area_entrega_repo.consultar_frete(municipio, bairro)

        # Se não encontrou frete, tenta resolver o termo via cache + web_search.
        # Cobre o caso em que a IA registrou um bairro como município
        # (ex: municipio="Bangu" → resolve para municipio="Rio de Janeiro", bairro="Bangu").
        if valor_frete is None:
            from agente_2w.tools.resolver_bairro import resolver_bairro_municipio
            # Tenta bairro primeiro; depois o município (pode ser bairro mal classificado)
            for termo_tentativa in filter(None, [bairro, municipio]):
                bairro_res, municipio_res, ambiguos = resolver_bairro_municipio(termo_tentativa)

                if ambiguos:
                    # Localidade existe em 2+ municípios cobertos — não é possível
                    # determinar automaticamente. Registrar fato para que o agente
                    # pergunte ao cliente qual cidade.
                    contexto_repo.registrar_fato(ContextoConversaCreate(
                        sessao_chat_id=sessao_id,
                        chave=ChaveContexto.MUNICIPIO_AMBIGUO,
                        valor_texto=", ".join(ambiguos),
                        valor_json={"municipios": ambiguos, "termo": termo_tentativa},
                        tipo_de_verdade=TipoDeVerdade.validado_tool,
                        nivel_confirmacao=NivelConfirmacao.nenhum,
                        fonte=OrigemContexto.backend,
                    ))
                    logger.info(
                        "Municipio ambiguo para '%s': %s — aguardando esclarecimento do cliente",
                        termo_tentativa, ambiguos,
                    )
                    return  # agente vai perguntar; não registra frete ainda

                if municipio_res:
                    valor_frete = area_entrega_repo.consultar_frete(
                        municipio_res, bairro_res or termo_tentativa
                    )
                    if valor_frete is not None:
                        logger.info(
                            "Localidade resolvida via web_search: '%s' → %s / %s",
                            termo_tentativa, municipio_res, bairro_res,
                        )
                        municipio = municipio_res
                        bairro = bairro_res or termo_tentativa
                        break

        if valor_frete is not None:
            # Limpar frete_nao_coberto antigo (mutuamente exclusivo)
            try:
                contexto_repo.desativar_fato_anterior(sessao_id, ChaveContexto.FRETE_NAO_COBERTO)
            except Exception:
                pass
            contexto_repo.registrar_fato(ContextoConversaCreate(
                sessao_chat_id=sessao_id,
                chave=ChaveContexto.FRETE_VALOR,
                valor_texto=str(valor_frete),
                valor_json=None,
                tipo_de_verdade=TipoDeVerdade.validado_tool,
                nivel_confirmacao=NivelConfirmacao.nenhum,
                fonte=OrigemContexto.backend,
            ))
            logger.info("Frete registrado: %s / %s = R$%s", municipio, bairro, valor_frete)
        else:
            # Limpar frete_valor antigo (mutuamente exclusivo)
            try:
                contexto_repo.desativar_fato_anterior(sessao_id, ChaveContexto.FRETE_VALOR)
            except Exception:
                pass
            contexto_repo.registrar_fato(ContextoConversaCreate(
                sessao_chat_id=sessao_id,
                chave=ChaveContexto.FRETE_NAO_COBERTO,
                valor_texto=municipio,
                valor_json=None,
                tipo_de_verdade=TipoDeVerdade.validado_tool,
                nivel_confirmacao=NivelConfirmacao.nenhum,
                fonte=OrigemContexto.backend,
            ))
            logger.info("Municipio sem cobertura de entrega: %s", municipio)

    except Exception:
        logger.exception("Falha ao consultar frete para sessao %s", sessao_id)
