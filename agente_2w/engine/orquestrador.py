"""Orquestrador — loop completo de um turno do agente."""

import logging
from uuid import UUID
from datetime import datetime, timezone

from agente_2w.db import (
    sessao_repo,
    mensagem_repo,
    contexto_repo,
    item_provisorio_repo,
    cliente_repo,
)
from agente_2w.engine.montador_contexto import montar_contexto
from agente_2w.engine.maquina_estados import transicao_permitida, motivo_bloqueio
from agente_2w.engine.promotor import promover_para_pedido, validar_pre_condicoes, cancelar_pedido_sessao, alterar_pedido_sessao, ErroPromocao
from agente_2w.ia.agente import chamar_agente
from agente_2w.ia.parser_envelope import parse_resposta, ParseError
from agente_2w.enums.enums import (
    Direcao,
    Remetente,
    TipoDeVerdade,
    NivelConfirmacao,
    OrigemContexto,
    StatusSessao,
    StatusItemProvisorio,
)
from agente_2w.constantes import ChaveContexto
from agente_2w.schemas.mensagem_chat import MensagemChatCreate
from agente_2w.schemas.contexto_conversa import ContextoConversaCreate
from agente_2w.schemas.item_provisorio import ItemProvisorioCreate

logger = logging.getLogger(__name__)

MENSAGEM_FALHA_SEGURA = (
    "Desculpe, tive um problema ao processar sua mensagem. "
    "Pode repetir ou reformular?"
)

MAX_RETRIES = 2


def _valor_para_contexto(valor):
    """Separa valor em (valor_texto, valor_json) conforme o tipo."""
    if isinstance(valor, (dict, list)):
        return None, valor
    if valor is not None:
        return str(valor), None
    return None, None


def _chamar_e_validar(contexto, mensagem_texto: str):
    """Chama IA, parseia e valida. Retry com correcao se envelope invalido.

    Retorna tupla (EnvelopeIA, pneus_encontrados) ou (None, []).
    pneus_encontrados: lista de dicts com pneu_id/posicao/preco_venda extraidos das tools.
    """
    etapa = contexto.sessao.etapa_atual.value
    acoes = ", ".join(contexto.acoes_permitidas)
    todos_pneus: list[dict] = []

    for tentativa in range(1 + MAX_RETRIES):
        # Na primeira tentativa, mensagem normal. No retry, mensagem com correcao.
        if tentativa == 0:
            msg = mensagem_texto
        else:
            from agente_2w.engine.maquina_estados import proximas_etapas
            proximas = [e.value for e in proximas_etapas(contexto.sessao.etapa_atual)]
            etapas_validas = [etapa] + proximas

            proxima_etapa = proximas[0] if proximas else etapa
            msg = (
                f"[MENSAGEM ORIGINAL DO CLIENTE]: {mensagem_texto}\n\n"
                f"[CORRECAO OBRIGATORIA DO BACKEND]: Sua resposta foi REJEITADA.\n"
                f"Erros encontrados:\n"
                + "\n".join(f"- {e}" for e in erros_anteriores)
                + f"\n\nREGRAS OBRIGATORIAS:"
                f"\n1. etapa_atual DEVE ser uma destas: {', '.join(etapas_validas)}"
                f"\n2. acoes_sugeridas DEVEM conter apenas acoes desta lista: [{acoes}]"
                f"\n3. NAO transicione para etapa que nao esta na lista acima"
                f"\n\nFORMATO OBRIGATORIO para este turno:"
                f'\n{{"etapa_atual": "{proxima_etapa}", "acoes_sugeridas": ["{(acoes.split(", ")[0] if acoes else "responder_incerteza_segura")}"], '
                f'"mensagem_cliente": "...(sua resposta ao cliente)...", '
                f'"intencao_atual": "...", "confianca": "alta", '
                f'"fatos_observados": [], "fatos_inferidos": [], '
                f'"mudancas_contexto": [], "mudancas_itens": [], "bloqueios_identificados": []}}'
                f"\n\nRetorne APENAS o JSON corrigido, sem texto antes ou depois."
            )
            logger.info("Retry %d com correcao", tentativa)

        try:
            resposta_bruta, pneus_da_chamada = chamar_agente(contexto, msg)
            todos_pneus.extend(pneus_da_chamada)
        except Exception as e:
            logger.error("Erro na chamada da IA (tentativa %d): %s", tentativa, e)
            return None, []

        try:
            envelope, erros_validacao = parse_resposta(resposta_bruta, contexto)
        except ParseError as e:
            logger.warning("ParseError (tentativa %d): %s", tentativa, e.mensagem)
            erros_anteriores = [e.mensagem]
            continue

        if not erros_validacao:
            return envelope, todos_pneus

        logger.warning(
            "Envelope invalido (tentativa %d): %s",
            tentativa, "; ".join(erros_validacao),
        )
        erros_anteriores = erros_validacao

    logger.error("IA falhou apos %d tentativas", 1 + MAX_RETRIES)
    return None, []


def _persistir_pneus_encontrados(sessao_id: UUID, pneus: list[dict]) -> None:
    """Persiste pneus encontrados no contexto para uso em turnos seguintes (ex: oferta).

    Chave: 'ultimos_pneus_encontrados' — sobrescreve a anterior via registrar_fato.
    """
    if not pneus:
        return
    vistos: set = set()
    unicos = []
    for p in pneus:
        pid = p.get("pneu_id")
        if pid and pid not in vistos:
            vistos.add(pid)
            unicos.append(p)
    if not unicos:
        return
    try:
        contexto_repo.registrar_fato(ContextoConversaCreate(
            sessao_chat_id=sessao_id,
            chave="ultimos_pneus_encontrados",
            valor_texto=None,
            valor_json=unicos,
            tipo_de_verdade=TipoDeVerdade.validado_tool,
            nivel_confirmacao=NivelConfirmacao.nenhum,
            fonte=OrigemContexto.backend,
        ))
        logger.debug("Pneus persistidos no contexto: %s", [p["pneu_id"] for p in unicos])
    except Exception as e:
        logger.warning("Erro ao persistir pneus encontrados: %s", e)


def _atualizar_nome_cliente(sessao_id: UUID, cliente_id) -> None:
    """Se nome_cliente foi registrado nos fatos e o cliente ainda nao tem nome, persiste."""
    try:
        cliente = cliente_repo.buscar_cliente_por_id(cliente_id)
        if not cliente or cliente.nome:
            return
        fato = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.NOME_CLIENTE)
        if fato and fato.valor_texto:
            cliente_repo.atualizar_cliente(cliente_id, {"nome": fato.valor_texto})
            logger.info("Nome cliente %s atualizado: %s", cliente_id, fato.valor_texto)
    except Exception as e:
        logger.warning("Falha ao atualizar nome do cliente: %s", e)


def _persistir_saida(sessao_id: UUID, texto: str) -> None:
    """Persiste mensagem de saida do agente."""
    try:
        mensagem_repo.criar_mensagem(MensagemChatCreate(
            sessao_chat_id=sessao_id,
            direcao=Direcao.saida,
            remetente=Remetente.agente,
            conteudo_texto=texto,
            criado_em=datetime.now(timezone.utc),
        ))
    except Exception as e:
        logger.error("Erro ao persistir mensagem de saida: %s", e)


def _aplicar_fatos_observados(sessao_id: UUID, fatos, mensagem_id: UUID) -> None:
    """Registra fatos observados (extraidos da mensagem do cliente)."""
    for fato in fatos:
        valor_texto, valor_json = _valor_para_contexto(fato.valor)
        try:
            contexto_repo.registrar_fato(ContextoConversaCreate(
                sessao_chat_id=sessao_id,
                chave=fato.chave,
                valor_texto=valor_texto,
                valor_json=valor_json,
                tipo_de_verdade=TipoDeVerdade.observado,
                nivel_confirmacao=NivelConfirmacao.nenhum,
                fonte=OrigemContexto.mensagem_cliente,
                mensagem_chat_id=mensagem_id,
            ))
        except Exception as e:
            logger.warning("Erro ao registrar fato observado '%s': %s", fato.chave, e)


def _aplicar_fatos_inferidos(sessao_id: UUID, fatos) -> None:
    """Registra fatos inferidos pela IA (com justificativa)."""
    for fato in fatos:
        valor_texto, valor_json = _valor_para_contexto(fato.valor)
        try:
            contexto_repo.registrar_fato(ContextoConversaCreate(
                sessao_chat_id=sessao_id,
                chave=fato.chave,
                valor_texto=valor_texto,
                valor_json=valor_json,
                tipo_de_verdade=TipoDeVerdade.inferido,
                nivel_confirmacao=NivelConfirmacao.nenhum,
                fonte=OrigemContexto.inferido_ia,
                observacao=fato.justificativa,
            ))
        except Exception as e:
            logger.warning("Erro ao registrar fato inferido '%s': %s", fato.chave, e)


def _aplicar_mudancas_contexto(sessao_id: UUID, mudancas) -> None:
    """Aplica mudancas de contexto propostas pela IA."""
    for mudanca in mudancas:
        valor_texto, valor_json = _valor_para_contexto(mudanca.valor_novo)
        try:
            contexto_repo.registrar_fato(ContextoConversaCreate(
                sessao_chat_id=sessao_id,
                chave=mudanca.chave,
                valor_texto=valor_texto,
                valor_json=valor_json,
                tipo_de_verdade=TipoDeVerdade.inferido,
                nivel_confirmacao=NivelConfirmacao.nenhum,
                fonte=OrigemContexto.inferido_ia,
                observacao=mudanca.motivo,
            ))
        except Exception as e:
            logger.warning("Erro ao aplicar mudanca contexto '%s': %s", mudanca.chave, e)


def _aplicar_mudancas_itens(sessao_id: UUID, mudancas, pneus_encontrados: list[dict] | None = None) -> None:
    """Aplica mudancas propostas pela IA em itens provisorios.

    pneus_encontrados: pneu_ids extraidos das tools (fallback se IA nao passar UUID).
    """
    pneus_encontrados = pneus_encontrados or []

    for mudanca in mudancas:
        try:
            if mudanca.acao == "criar":
                dados = mudanca.dados or {}
                pneu_id_raw = dados.get("pneu_id")
                posicao = dados.get("posicao")

                # Validar UUID antes de usar — rejeitar silenciosamente se malformado
                pneu_uuid = None
                if pneu_id_raw:
                    try:
                        pneu_uuid = UUID(str(pneu_id_raw))
                    except (ValueError, AttributeError):
                        logger.warning(
                            "pneu_id invalido ignorado: '%s'. Tentando auto-enriquecer.",
                            pneu_id_raw,
                        )

                # --- AUTO-ENRIQUECIMENTO: se IA nao passou UUID valido, buscar nos resultados de tool ---
                if pneu_uuid is None and pneus_encontrados:
                    # Deduplica por pneu_id
                    vistos = set()
                    unicos = []
                    for p in pneus_encontrados:
                        pid = p.get("pneu_id")
                        if pid and pid not in vistos:
                            vistos.add(pid)
                            unicos.append(p)

                    match = None
                    # Tenta match por posicao
                    if posicao:
                        match = next(
                            (p for p in unicos if p.get("posicao") and posicao in str(p["posicao"])),
                            None,
                        )
                    # Se so tem 1 pneu nos resultados, usa direto
                    if not match and len(unicos) == 1:
                        match = unicos[0]

                    if match:
                        try:
                            pneu_uuid = UUID(str(match["pneu_id"]))
                            logger.info(
                                "pneu_id auto-enriquecido do resultado de tool: %s",
                                pneu_uuid,
                            )
                            # Tambem preencher preco se ausente
                            if not dados.get("preco_unitario_sugerido") and match.get("preco_venda"):
                                dados["preco_unitario_sugerido"] = float(match["preco_venda"])
                                logger.info("preco_unitario_sugerido auto-enriquecido: %s", match["preco_venda"])
                        except (ValueError, AttributeError):
                            pass

                # Se tem pneu_id valido, criar ja como selecionado_cliente
                status_inicial = (
                    StatusItemProvisorio.selecionado_cliente
                    if pneu_uuid
                    else StatusItemProvisorio.sugerido
                )

                item_provisorio_repo.criar_item(ItemProvisorioCreate(
                    sessao_chat_id=sessao_id,
                    status_item=status_inicial,
                    pneu_id=pneu_uuid,
                    posicao=posicao,
                    quantidade=dados.get("quantidade", 1),
                    preco_unitario_sugerido=dados.get("preco_unitario_sugerido"),
                    observacao=dados.get("observacao"),
                ))
                logger.info(
                    "Item provisorio criado para sessao %s (pneu_id=%s, status=%s)",
                    sessao_id, pneu_uuid, status_inicial.value,
                )

            elif mudanca.acao in ("confirmar", "rejeitar", "cancelar", "atualizar"):
                if not mudanca.item_provisorio_id:
                    logger.warning("Mudanca '%s' sem item_provisorio_id", mudanca.acao)
                    continue

                item_id = UUID(mudanca.item_provisorio_id)

                # Auto-correcao: modelo as vezes passa pneu_id no lugar de item_provisorio_id
                itens_ativos = item_provisorio_repo.listar_itens_ativos_por_sessao(sessao_id)
                item_direto = next((i for i in itens_ativos if i.id == item_id), None)
                if item_direto is None:
                    item_por_pneu = next(
                        (i for i in itens_ativos if i.pneu_id and str(i.pneu_id) == str(item_id)),
                        None,
                    )
                    if item_por_pneu:
                        logger.info(
                            "Auto-correcao item_provisorio_id: '%s' era pneu_id, "
                            "usando item %s",
                            item_id, item_por_pneu.id,
                        )
                        item_id = item_por_pneu.id
                    elif len(itens_ativos) == 1:
                        logger.info(
                            "Auto-correcao item_provisorio_id: UUID '%s' nao encontrado, "
                            "usando unico item ativo %s",
                            item_id, itens_ativos[0].id,
                        )
                        item_id = itens_ativos[0].id
                    else:
                        logger.warning(
                            "Mudanca '%s': item_provisorio_id '%s' nao encontrado e "
                            "ha %d itens ativos — impossivel auto-corrigir",
                            mudanca.acao, item_id, len(itens_ativos),
                        )
                        continue

                if mudanca.acao == "confirmar":
                    item_provisorio_repo.atualizar_status_item(
                        item_id, StatusItemProvisorio.selecionado_cliente,
                    )
                elif mudanca.acao == "rejeitar":
                    item_provisorio_repo.atualizar_status_item(
                        item_id, StatusItemProvisorio.rejeitado,
                    )
                elif mudanca.acao == "cancelar":
                    item_provisorio_repo.atualizar_status_item(
                        item_id, StatusItemProvisorio.cancelado,
                    )
                elif mudanca.acao == "atualizar":
                    dados = mudanca.dados or {}
                    if dados.get("pneu_id"):
                        try:
                            item_provisorio_repo.vincular_pneu(
                                item_id, UUID(dados["pneu_id"]),
                            )
                        except (ValueError, AttributeError):
                            logger.warning("pneu_id invalido em atualizar: '%s'", dados["pneu_id"])
                    if dados.get("status_item"):
                        status_str = dados["status_item"]
                        # Bloquear IA de setar promovido — exclusivo do promotor
                        if status_str == "promovido":
                            logger.warning(
                                "IA tentou setar status_item=promovido no item %s. Bloqueado.",
                                item_id,
                            )
                        else:
                            status = StatusItemProvisorio(status_str)
                            item_provisorio_repo.atualizar_status_item(item_id, status)

        except Exception as e:
            logger.warning("Erro ao aplicar mudanca item '%s': %s", mudanca.acao, e)


def _parsear_localidade_endereco(fato) -> tuple[str | None, str | None]:
    """Extrai (municipio, bairro) do fato endereco_entrega.

    Tenta primeiro valor_json estruturado, depois parseia valor_texto livre.
    Formato tipico: "Rua X, 123, Bairro Centro, Caxias do Sul, RS"
    """
    import re

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
    except Exception as e:
        logger.warning("Falha ao atualizar localidade do cliente: %s", e)


def _despachar_acoes(sessao_id: UUID, acoes: list[str]) -> None:
    """Despacha acoes que requerem execucao backend.

    A maioria das acoes sao semanticas (a IA ja executou tools via function
    calling). Apenas ``converter_em_pedido`` dispara logica backend real.
    """
    for acao in acoes:
        if acao == "converter_em_pedido":
            try:
                pedido = promover_para_pedido(sessao_id)
                logger.info("Pedido criado: %s (valor_total=%s)", pedido.id, pedido.valor_total)
                sessao = sessao_repo.buscar_sessao_por_id(sessao_id)
                if sessao and sessao.cliente_id:
                    _atualizar_localidade_cliente(sessao_id, sessao.cliente_id)
            except (ErroPromocao, ValueError) as e:
                logger.warning("Falha ao converter em pedido: %s", e)


def _avaliar_transicao(sessao_id: UUID, etapa_atual, etapa_proposta) -> None:
    """Avalia e aplica transicao de etapa, ou registra bloqueio."""
    if etapa_proposta == etapa_atual:
        return

    if transicao_permitida(etapa_atual, etapa_proposta):
        sessao_repo.atualizar_etapa(sessao_id, etapa_proposta)
        logger.info("Etapa: %s -> %s", etapa_atual.value, etapa_proposta.value)
    else:
        motivo = motivo_bloqueio(etapa_atual, etapa_proposta)
        sessao_repo.atualizar_status(
            sessao_id,
            StatusSessao.bloqueada,
            codigo_motivo="transicao_invalida",
            mensagem_motivo=motivo,
            campo_relacionado="etapa_atual",
            acao_bloqueada=f"transicao_para_{etapa_proposta.value}",
        )
        logger.warning("Transicao bloqueada: %s", motivo)


def processar_turno(
    sessao_id: UUID,
    mensagem_texto: str,
    criado_em: datetime | None = None,
    message_id_externo: str | None = None,
) -> str:
    """Processa um turno completo da conversa.

    Retorna a mensagem em linguagem natural para enviar ao cliente.
    """
    agora = criado_em or datetime.now(timezone.utc)

    # --- 1. Persistir mensagem de entrada ---
    msg_entrada = mensagem_repo.criar_mensagem(MensagemChatCreate(
        sessao_chat_id=sessao_id,
        direcao=Direcao.entrada,
        remetente=Remetente.cliente,
        conteudo_texto=mensagem_texto,
        criado_em=agora,
        message_id_externo=message_id_externo,
    ))
    logger.info("Mensagem entrada persistida: %s", msg_entrada.id)

    # --- 2. Resolver cliente automaticamente se necessario ---
    sessao = sessao_repo.buscar_sessao_por_id(sessao_id)
    if sessao and not sessao.cliente_id:
        try:
            cliente = cliente_repo.resolver_ou_criar_cliente(sessao.contato_externo)
            sessao_repo.vincular_cliente(sessao_id, cliente.id)
            logger.info("Cliente resolvido: %s", cliente.id)
        except Exception as e:
            logger.warning("Falha ao resolver cliente: %s", e)

    # --- 3. Montar contexto executavel ---
    contexto = montar_contexto(sessao_id)

    # --- 4 e 5. Chamar IA + parsear/validar com retry ---
    envelope, pneus_encontrados = _chamar_e_validar(contexto, mensagem_texto)
    if envelope is None:
        _persistir_saida(sessao_id, MENSAGEM_FALHA_SEGURA)
        return MENSAGEM_FALHA_SEGURA

    if pneus_encontrados:
        logger.info(
            "pneus coletados das tools: %s",
            [p["pneu_id"] for p in pneus_encontrados],
        )
        # Persistir no contexto para turnos seguintes (ex: oferta sem tool call)
        _persistir_pneus_encontrados(sessao_id, pneus_encontrados)
    else:
        # Recuperar pneus do contexto se este turno nao fez tool calls de busca
        fato_pneus = contexto_repo.buscar_fato_ativo(sessao_id, "ultimos_pneus_encontrados")
        if fato_pneus and fato_pneus.valor_json:
            pneus_encontrados = fato_pneus.valor_json
            logger.debug(
                "pneus_encontrados recuperados do contexto: %d pneus",
                len(pneus_encontrados),
            )

    # --- 6. Aplicar fatos observados ---
    _aplicar_fatos_observados(sessao_id, envelope.fatos_observados, msg_entrada.id)

    # --- 7. Aplicar fatos inferidos ---
    _aplicar_fatos_inferidos(sessao_id, envelope.fatos_inferidos)

    # --- 7b. Persistir nome do cliente se foi registrado neste turno ---
    sessao_apos_fatos = sessao_repo.buscar_sessao_por_id(sessao_id)
    if sessao_apos_fatos and sessao_apos_fatos.cliente_id:
        _atualizar_nome_cliente(sessao_id, sessao_apos_fatos.cliente_id)

    # --- 7c. Cancelamento solicitado via fato ---
    fato_cancel = contexto_repo.buscar_fato_ativo(sessao_id, "pedido_cancelamento_solicitado")
    if fato_cancel:
        cancelado = cancelar_pedido_sessao(sessao_id)
        if cancelado:
            logger.info("Pedido da sessao %s cancelado via fato", sessao_id)
        # Desativa o fato para nao cancelar de novo nos proximos turnos
        try:
            contexto_repo.desativar_fato_anterior(sessao_id, "pedido_cancelamento_solicitado")
        except Exception as e:
            logger.warning("Falha ao desativar fato cancelamento: %s", e)

    # --- 8. Aplicar mudancas de contexto ---
    _aplicar_mudancas_contexto(sessao_id, envelope.mudancas_contexto)

    # --- 8b. Sincronizar alteracoes com pedido existente (item 5) ---
    # Se ja existe pedido confirmado e contexto mudou, atualiza entrega/pagamento/endereco
    from agente_2w.enums.enums import EtapaFluxo
    if envelope.etapa_atual == EtapaFluxo.fechamento:
        try:
            alterado = alterar_pedido_sessao(sessao_id)
            if alterado:
                logger.info("Pedido da sessao %s atualizado apos mudanca de contexto", sessao_id)
        except Exception as e:
            logger.warning("Falha ao sincronizar alteracoes do pedido: %s", e)

    # --- 9. Aplicar mudancas de itens (com auto-enriquecimento de pneu_id) ---
    _aplicar_mudancas_itens(sessao_id, envelope.mudancas_itens, pneus_encontrados)

    # --- 10. Despachar acoes sugeridas ---
    _despachar_acoes(sessao_id, envelope.acoes_sugeridas)

    # --- 11. Avaliar transicao de etapa ---
    _avaliar_transicao(sessao_id, contexto.sessao.etapa_atual, envelope.etapa_atual)

    # --- 12. Auto-promover em fechamento se pre-condicoes ok ---
    # Se a etapa resultante e fechamento e o promotor nao foi chamado
    # via acoes_sugeridas, verificar se podemos promover automaticamente.
    etapa_resultante = envelope.etapa_atual
    ja_tentou_promover = "converter_em_pedido" in envelope.acoes_sugeridas
    if etapa_resultante.value == "fechamento" and not ja_tentou_promover:
        erros_pre = validar_pre_condicoes(sessao_id)
        if not erros_pre:
            try:
                pedido = promover_para_pedido(sessao_id)
                logger.info(
                    "Auto-promocao em fechamento: pedido %s (valor=%s)",
                    pedido.id, pedido.valor_total,
                )
                sessao_atual = sessao_repo.buscar_sessao_por_id(sessao_id)
                if sessao_atual and sessao_atual.cliente_id:
                    _atualizar_localidade_cliente(sessao_id, sessao_atual.cliente_id)
            except (ErroPromocao, ValueError) as e:
                logger.warning("Auto-promocao falhou: %s", e)
        else:
            logger.debug("Auto-promocao nao acionada: %s", "; ".join(erros_pre))

    # --- 13. Persistir mensagem de saida ---
    _persistir_saida(sessao_id, envelope.mensagem_cliente)

    # --- 14. Retornar mensagem ---
    return envelope.mensagem_cliente
