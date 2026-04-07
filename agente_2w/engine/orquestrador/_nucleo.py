"""Orquestrador — loop completo de um turno do agente."""

import logging
from uuid import UUID
from datetime import datetime, timezone

from agente_2w.config import MAX_RETRIES
from agente_2w.db import (
    sessao_repo,
    mensagem_repo,
    contexto_repo,
    item_provisorio_repo,
    cliente_repo,
)
from agente_2w.engine.sessao_timeout import (
    avaliar_sessao,
    SituacaoSessao,
    TIMEOUT_BLOQUEADA_HORAS,
    TIMEOUT_SESSAO_DIAS,
)
from agente_2w.engine.montador_contexto import montar_contexto
from agente_2w.engine.maquina_estados import transicao_permitida, motivo_bloqueio, proximas_etapas
from agente_2w.engine.promotor import promover_para_pedido, validar_pre_condicoes, cancelar_pedido_sessao, alterar_pedido_sessao, ErroPromocao
from agente_2w.ia.agente import chamar_agente
from agente_2w.ia.parser_envelope import parse_resposta, ParseError
from agente_2w.ia.prompt_retry import montar_prompt_retry
from agente_2w.enums.enums import (
    Direcao,
    EtapaFluxo,
    Remetente,
    TipoDeVerdade,
    NivelConfirmacao,
    OrigemContexto,
    StatusSessao,
    StatusItemProvisorio,
)
from agente_2w.constantes import ChaveContexto
from agente_2w.schemas.mensagem_chat import MensagemChatCreate
from agente_2w.schemas.sessao_chat import SessaoChatCreate
from agente_2w.schemas.contexto_conversa import ContextoConversaCreate
from agente_2w.schemas.item_provisorio import ItemProvisorioCreate
from agente_2w.schemas.resposta_turno import RespostaTurno

logger = logging.getLogger(__name__)

MENSAGEM_FALHA_SEGURA = (
    "Desculpe, tive um problema ao processar sua mensagem. "
    "Pode repetir ou reformular?"
)

def _valor_para_contexto(valor):
    """Separa valor em (valor_texto, valor_json) conforme o tipo."""
    if isinstance(valor, (dict, list)):
        return None, valor
    if valor is not None:
        return str(valor), None
    return None, None


from agente_2w.engine.orquestrador.confirmacao_pedido import (  # noqa: E402
    _montar_confirmacao_pedido,
)


# ---------- Keywords para extracao de fatos estruturados ----------

from agente_2w.engine.orquestrador.fatos_fallback import (  # noqa: E402
    _extrair_fatos_estruturados_fallback,
)


def _resolver_timeout(sessao) -> UUID:
    """Avalia o estado de timeout da sessao e retorna o sessao_id a usar.

    Pode retornar o mesmo ID (sessao ok ou desbloqueada) ou um novo ID
    (sessao expirada — a antiga e fechada e uma nova e criada no lugar).

    Nunca levanta excecao: em caso de falha, retorna o sessao_id original
    para nao interromper o atendimento.
    """
    try:
        situacao = avaliar_sessao(sessao)

        if situacao == SituacaoSessao.ok:
            return sessao.id

        if situacao == SituacaoSessao.bloqueada_antiga:
            sessao_repo.atualizar_status(sessao.id, StatusSessao.ativa)
            logger.info(
                "Sessao %s desbloqueada automaticamente (bloqueada ha mais de %dh sem interacao)",
                sessao.id, TIMEOUT_BLOQUEADA_HORAS,
            )
            return sessao.id

        # expirada_com_contexto ou expirada_sem_contexto
        sessao_repo.fechar_sessao(sessao.id)
        # Cancelar itens provisorios orfaos da sessao expirada
        try:
            itens_orfaos = item_provisorio_repo.listar_itens_ativos_por_sessao(sessao.id)
            for item in itens_orfaos:
                item_provisorio_repo.atualizar_status_item(
                    item.id, StatusItemProvisorio.cancelado,
                )
            if itens_orfaos:
                logger.info(
                    "Sessao expirada %s: %d itens provisorios cancelados",
                    sessao.id, len(itens_orfaos),
                )
        except Exception:
            logger.exception("Falha ao cancelar itens da sessao expirada %s", sessao.id)
        nova = sessao_repo.criar_sessao(SessaoChatCreate(
            canal=sessao.canal,
            contato_externo=sessao.contato_externo,
            etapa_atual=EtapaFluxo.identificacao,
            status_sessao=StatusSessao.ativa,
        ))
        logger.info(
            "Sessao %s encerrada por inatividade (%dd sem interacao, situacao=%s). "
            "Nova sessao criada: %s",
            sessao.id, TIMEOUT_SESSAO_DIAS, situacao.value, nova.id,
        )
        return nova.id

    except Exception:
        logger.exception(
            "Falha ao avaliar timeout da sessao %s — continuando com sessao original",
            sessao.id,
        )
        return sessao.id


def _chamar_e_validar(contexto, mensagem_texto: str, imagens: list[str] | None = None):
    """Chama IA, parseia e valida. Retry com correcao se envelope invalido.

    Retorna tupla (EnvelopeIA, pneus_encontrados) ou (None, []).
    pneus_encontrados: lista de dicts com pneu_id/posicao/preco_venda extraidos das tools.
    """
    etapa = contexto.sessao.etapa_atual.value
    todos_pneus: list[dict] = []
    erros_anteriores: list[str] = []

    for tentativa in range(1 + MAX_RETRIES):
        # Na primeira tentativa, mensagem normal. No retry, mensagem com correcao.
        if tentativa == 0:
            msg = mensagem_texto
        else:
            proximas = [e.value for e in proximas_etapas(contexto.sessao.etapa_atual)]
            etapas_validas = [etapa] + proximas
            proxima_etapa = proximas[0] if proximas else etapa
            msg = montar_prompt_retry(
                mensagem_original=mensagem_texto,
                erros=erros_anteriores,
                etapas_validas=etapas_validas,
                acoes_permitidas=contexto.acoes_permitidas,
                proxima_etapa=proxima_etapa,
            )
            logger.info("Retry %d com correcao", tentativa)

        try:
            # Imagens só na primeira tentativa — retry usa só texto de correção
            imgs = imagens if tentativa == 0 else None
            resposta_bruta, pneus_da_chamada = chamar_agente(contexto, msg, imagens=imgs)
            todos_pneus.extend(pneus_da_chamada)
        except Exception:
            logger.exception("Erro na chamada da IA (tentativa %d)", tentativa)
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

    Deduplicacao inteligente: quando o mesmo pneu_id aparece mais de uma vez
    (ex: buscar_pneus_por_moto sem preco + consultar_estoque com preco), o
    merge preserva todos os campos nao-nulos — especialmente preco_venda.
    Isso evita que o preco seja perdido quando o item e criado num turno
    subsequente (causa raiz do loop em fechamento).
    """
    if not pneus:
        return
    merged: dict[str, dict] = {}
    for p in pneus:
        pid = p.get("pneu_id")
        if not pid:
            continue
        if pid not in merged:
            merged[pid] = dict(p)
        else:
            # Mescla: atualiza campos nulos no registro existente com valores do atual
            existente = merged[pid]
            for k, v in p.items():
                if v is not None and not existente.get(k):
                    existente[k] = v
    unicos = list(merged.values())
    if not unicos:
        return
    try:
        contexto_repo.registrar_fato(ContextoConversaCreate(
            sessao_chat_id=sessao_id,
            chave=ChaveContexto.ULTIMOS_PNEUS_ENCONTRADOS,
            valor_texto=None,
            valor_json=unicos,
            tipo_de_verdade=TipoDeVerdade.validado_tool,
            nivel_confirmacao=NivelConfirmacao.nenhum,
            fonte=OrigemContexto.backend,
        ))
        logger.debug("Pneus persistidos no contexto: %s", [p["pneu_id"] for p in unicos])
    except Exception:
        logger.exception("Erro ao persistir pneus encontrados")


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
    except Exception:
        logger.exception("Falha ao atualizar nome do cliente")


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
    except Exception:
        logger.exception("Erro ao persistir mensagem de saida")


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
        except Exception:
            logger.exception("Erro ao registrar fato observado '%s'", fato.chave)


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
        except Exception:
            logger.exception("Erro ao registrar fato inferido '%s'", fato.chave)


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
        except Exception:
            logger.exception("Erro ao aplicar mudanca contexto '%s'", mudanca.chave)


from agente_2w.engine.orquestrador.enriquecimento_itens import _aplicar_mudancas_itens  # noqa: E402


from agente_2w.engine.orquestrador.localidade_frete import (  # noqa: E402
    _atualizar_localidade_cliente,
    _consultar_e_registrar_frete,
)


from agente_2w.engine.orquestrador.guardrails import _aplicar_guardrail  # noqa: E402


def _despachar_acoes(sessao_id: UUID, acoes: list[str]):
    """Despacha acoes que requerem execucao backend.

    A maioria das acoes sao semanticas (a IA ja executou tools via function
    calling). Acoes com logica backend real:
    - converter_em_pedido → promotor
    - adicionar_outro_item → limpa contexto da busca anterior (pneus, medida, posicao)
    - finalizar_itens → registra que cliente nao quer mais itens (observabilidade)

    Retorna o Pedido criado se converter_em_pedido foi executado, None caso contrario.
    """
    pedido_criado = None
    for acao in acoes:
        if acao == "converter_em_pedido":
            try:
                pedido = promover_para_pedido(sessao_id)
                logger.info("Pedido #%s criado: %s (valor_total=%s)", pedido.numero_pedido, pedido.id, pedido.valor_total)
                pedido_criado = pedido
                sessao = sessao_repo.buscar_sessao_por_id(sessao_id)
                if sessao and sessao.cliente_id:
                    _atualizar_localidade_cliente(sessao_id, sessao.cliente_id)
            except (ErroPromocao, ValueError) as e:
                logger.warning("Falha ao converter em pedido: %s", e)
                erro_str = str(e)
                # Registrar erro para a LLM informar o cliente em vez de loopear
                try:
                    contexto_repo.registrar_fato(ContextoConversaCreate(
                        sessao_chat_id=sessao_id,
                        chave=ChaveContexto.ERRO_PROMOCAO,
                        valor_texto=erro_str,
                        valor_json=None,
                        tipo_de_verdade=TipoDeVerdade.validado_tool,
                        nivel_confirmacao=NivelConfirmacao.nenhum,
                        fonte=OrigemContexto.backend,
                    ))
                except Exception:
                    logger.exception("Falha ao registrar erro_promocao")

                # Auto-regressao: se erro de estoque, regredir para oferta
                if "estoque" in erro_str.lower():
                    logger.info("Auto-regressao (converter_em_pedido): fechamento -> oferta")
                    sessao_repo.atualizar_etapa(sessao_id, EtapaFluxo.oferta)
                    itens_ativos = item_provisorio_repo.listar_itens_ativos_por_sessao(sessao_id)
                    for item in itens_ativos:
                        if item.pneu_id and str(item.pneu_id) in erro_str:
                            item_provisorio_repo.atualizar_status_item(
                                item.id, StatusItemProvisorio.cancelado
                            )
                            logger.info("Item cancelado (estoque=0): %s", item.id)
                    contexto_repo.desativar_fato_anterior(sessao_id, "itens_finalizados")

        elif acao == "adicionar_outro_item":
            # Limpa contexto da busca anterior para que a proxima busca comece do zero.
            # Sem isso, medida_informada e posicao_pneu da moto anterior contaminam
            # a busca da nova moto — o auto-enriquecimento usaria pneu_id errado.
            _FATOS_A_LIMPAR = [
                ChaveContexto.ULTIMOS_PNEUS_ENCONTRADOS,
                ChaveContexto.MEDIDA_INFORMADA,
                ChaveContexto.POSICAO_PNEU,
                ChaveContexto.SEM_PREFERENCIA_MARCA,        # evita que o "nao" da moto anterior
                ChaveContexto.CLIENTE_RECUSOU_OPCAO_ATUAL,  # confunda a busca da nova moto
            ]
            for chave in _FATOS_A_LIMPAR:
                try:
                    contexto_repo.desativar_fato_anterior(sessao_id, chave)
                    logger.info("Fato '%s' limpo para nova busca (adicionar_outro_item)", chave)
                except Exception:
                    logger.exception("Falha ao limpar fato '%s'", chave)

        elif acao == "finalizar_itens":
            # Cliente confirmou que nao quer mais itens — registra para observabilidade.
            try:
                contexto_repo.registrar_fato(ContextoConversaCreate(
                    sessao_chat_id=sessao_id,
                    chave=ChaveContexto.ITENS_FINALIZADOS,
                    valor_texto="true",
                    valor_json=None,
                    tipo_de_verdade=TipoDeVerdade.confirmado_cliente,
                    nivel_confirmacao=NivelConfirmacao.confirmado_cliente,
                    fonte=OrigemContexto.backend,
                ))
                logger.info("itens_finalizados registrado — cliente nao quer mais itens")
            except Exception:
                logger.exception("Falha ao registrar itens_finalizados")

    return pedido_criado


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


import re as _re

_REGEX_PEDIU_FOTO = _re.compile(
    r"(?:foto|imagem|ver o pneu|ver ele|mostra|como .{0,6} pneu|manda.{0,6}foto|quero ver|"
    r"tem como ver|deixa eu ver|me mostra|posso ver)",
    _re.IGNORECASE,
)


def _cliente_pediu_foto(mensagem: str) -> bool:
    """Retorna True se a mensagem do cliente indica pedido de foto/imagem."""
    return bool(_REGEX_PEDIU_FOTO.search(mensagem))


def processar_turno(
    sessao_id: UUID,
    mensagem_texto: str,
    criado_em: datetime | None = None,
    message_id_externo: str | None = None,
    imagens: list[str] | None = None,
) -> RespostaTurno:
    """Processa um turno completo da conversa.

    Retorna RespostaTurno com texto + URLs de fotos dos pneus encontrados.
    Retrocompatível com str (print, in, f-string funcionam).
    """
    agora = criado_em or datetime.now(timezone.utc)

    # --- 0a. Rejeitar mensagem vazia ---
    if not mensagem_texto or not mensagem_texto.strip():
        logger.warning("Mensagem vazia recebida para sessao %s", sessao_id)
        resposta = "Oi! Pode mandar sua mensagem que te ajudo. 😊"
        _persistir_saida(sessao_id, resposta)
        return RespostaTurno(texto=resposta)

    # --- 0. Resolver timeout da sessao ---
    # Deve acontecer antes de qualquer escrita para garantir que todos os
    # passos seguintes operem no sessao_id correto.
    sessao_pre = sessao_repo.buscar_sessao_por_id(sessao_id)
    if sessao_pre:
        sessao_id = _resolver_timeout(sessao_pre)

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
        except Exception:
            logger.exception("Falha ao resolver cliente")

    # --- 3. Montar contexto executavel ---
    try:
        contexto = montar_contexto(sessao_id)
    except Exception:
        logger.exception("Falha ao montar contexto para sessao %s", sessao_id)
        _persistir_saida(sessao_id, MENSAGEM_FALHA_SEGURA)
        return RespostaTurno(texto=MENSAGEM_FALHA_SEGURA)

    # --- 4 e 5. Chamar IA + parsear/validar com retry ---
    envelope, pneus_encontrados = _chamar_e_validar(contexto, mensagem_texto, imagens=imagens)
    if envelope is None:
        _persistir_saida(sessao_id, MENSAGEM_FALHA_SEGURA)
        return RespostaTurno(texto=MENSAGEM_FALHA_SEGURA)

    # --- 5b. Guardrail: corrigir acoes conflitantes antes de qualquer processamento ---
    envelope = _aplicar_guardrail(envelope, contexto.sessao.etapa_atual)

    if pneus_encontrados:
        logger.info(
            "pneus coletados das tools: %s",
            [p["pneu_id"] for p in pneus_encontrados],
        )
        # Persistir no contexto para turnos seguintes (ex: oferta sem tool call)
        _persistir_pneus_encontrados(sessao_id, pneus_encontrados)
    else:
        # Recuperar pneus do contexto se este turno nao fez tool calls de busca
        fato_pneus = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.ULTIMOS_PNEUS_ENCONTRADOS)
        if fato_pneus and fato_pneus.valor_json:
            pneus_encontrados = fato_pneus.valor_json
            logger.debug(
                "pneus_encontrados recuperados do contexto: %d pneus",
                len(pneus_encontrados),
            )

    # --- 6. Aplicar fatos observados ---
    _aplicar_fatos_observados(sessao_id, envelope.fatos_observados, msg_entrada.id)

    # --- 6b. Fallback: capturar forma_pagamento e tipo_entrega se IA nao registrou ---
    _extrair_fatos_estruturados_fallback(sessao_id, mensagem_texto, msg_entrada.id)

    # --- 7. Aplicar fatos inferidos ---
    _aplicar_fatos_inferidos(sessao_id, envelope.fatos_inferidos)

    # --- 7b. Persistir nome do cliente se foi registrado neste turno ---
    sessao_apos_fatos = sessao_repo.buscar_sessao_por_id(sessao_id)
    if sessao_apos_fatos and sessao_apos_fatos.cliente_id:
        _atualizar_nome_cliente(sessao_id, sessao_apos_fatos.cliente_id)

    # --- 7c. Cancelamento solicitado via fato ---
    fato_cancel = contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.PEDIDO_CANCELAMENTO_SOLICITADO)
    if fato_cancel:
        # Desativar ANTES de cancelar para evitar retrigger se cancelamento falhar parcialmente
        try:
            contexto_repo.desativar_fato_anterior(sessao_id, ChaveContexto.PEDIDO_CANCELAMENTO_SOLICITADO)
        except Exception:
            logger.exception("Falha ao desativar fato cancelamento")
        cancelado = cancelar_pedido_sessao(sessao_id)
        if cancelado:
            logger.info("Pedido da sessao %s cancelado via fato", sessao_id)

    # --- 8. Aplicar mudancas de contexto ---
    _aplicar_mudancas_contexto(sessao_id, envelope.mudancas_contexto)

    # --- 8b. Sincronizar alteracoes com pedido existente (item 5) ---
    # Se ja existe pedido confirmado e contexto mudou, atualiza entrega/pagamento/endereco
    if envelope.etapa_atual == EtapaFluxo.fechamento:
        try:
            alterado = alterar_pedido_sessao(sessao_id)
            if alterado:
                logger.info("Pedido da sessao %s atualizado apos mudanca de contexto", sessao_id)
        except Exception:
            logger.exception("Falha ao sincronizar alteracoes do pedido")

    # --- 8c. Consultar e registrar frete se entrega com municipio definido ---
    # Guarda se frete ja existia ANTES do calculo para detectar calculo novo neste turno
    _chaves_antes = {f.chave for f in contexto.fatos_ativos}
    _frete_ja_tinha = (
        ChaveContexto.FRETE_VALOR in _chaves_antes
        or ChaveContexto.FRETE_NAO_COBERTO in _chaves_antes
    )
    _consultar_e_registrar_frete(sessao_id)
    _frete_calculado_agora = not _frete_ja_tinha and (
        contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.FRETE_VALOR) is not None
        or contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.FRETE_NAO_COBERTO) is not None
    )
    # Tambem dispara follow-up quando municipio ambiguo foi detectado neste turno
    _ambiguo_agora = (
        ChaveContexto.MUNICIPIO_AMBIGUO not in _chaves_antes
        and contexto_repo.buscar_fato_ativo(sessao_id, ChaveContexto.MUNICIPIO_AMBIGUO) is not None
    )

    # --- 9. Aplicar mudancas de itens (com auto-enriquecimento de pneu_id) ---
    _aplicar_mudancas_itens(sessao_id, envelope.mudancas_itens, pneus_encontrados)

    # --- 9b. Rede de seguranca: confirmacao_item sem item criado ---
    # Se a etapa transicionou para confirmacao_item mas nenhum item provisorio
    # com pneu_id existe, criar automaticamente a partir de ultimos_pneus_encontrados.
    # Cobre casos onde o modelo nao incluiu mudancas_itens ao confirmar.
    if envelope.etapa_atual == EtapaFluxo.confirmacao_item:
        itens_existentes = item_provisorio_repo.listar_itens_ativos_por_sessao(sessao_id)
        itens_com_pneu = [i for i in itens_existentes if i.pneu_id]
        if not itens_com_pneu and pneus_encontrados:
            vistos: set = set()
            for p in pneus_encontrados:
                pid = p.get("pneu_id")
                if pid and pid not in vistos:
                    vistos.add(pid)
                    try:
                        pneu_uuid = UUID(str(pid))
                        posicao_pneu = p.get("posicao")
                        preco = float(p["preco_venda"]) if p.get("preco_venda") else None
                        item_provisorio_repo.criar_item(ItemProvisorioCreate(
                            sessao_chat_id=sessao_id,
                            status_item=StatusItemProvisorio.selecionado_cliente,
                            pneu_id=pneu_uuid,
                            posicao=posicao_pneu,
                            quantidade=1,
                            preco_unitario_sugerido=preco,
                        ))
                        logger.info(
                            "Rede de seguranca 9b: item criado automaticamente pneu_id=%s", pneu_uuid
                        )
                    except Exception:
                        logger.exception("Rede de seguranca 9b falhou")

    # --- 10. Despachar acoes sugeridas ---
    pedido_criado = _despachar_acoes(sessao_id, envelope.acoes_sugeridas)

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
                pedido_criado = promover_para_pedido(sessao_id)
                logger.info(
                    "Auto-promocao em fechamento: pedido #%s (valor=%s)",
                    pedido_criado.numero_pedido, pedido_criado.valor_total,
                )
                sessao_atual = sessao_repo.buscar_sessao_por_id(sessao_id)
                if sessao_atual and sessao_atual.cliente_id:
                    _atualizar_localidade_cliente(sessao_id, sessao_atual.cliente_id)
            except (ErroPromocao, ValueError) as e:
                logger.warning("Auto-promocao falhou: %s", e)
                # Registrar erro no contexto para que a LLM saiba e informe o cliente
                # (evita loop infinito de "Confirma o pedido?" quando estoque=0)
                try:
                    contexto_repo.registrar_fato(ContextoConversaCreate(
                        sessao_chat_id=sessao_id,
                        chave=ChaveContexto.ERRO_PROMOCAO,
                        valor_texto=str(e),
                        valor_json=None,
                        tipo_de_verdade=TipoDeVerdade.validado_tool,
                        nivel_confirmacao=NivelConfirmacao.nenhum,
                        fonte=OrigemContexto.backend,
                    ))
                except Exception:
                    logger.exception("Falha ao registrar erro_promocao no contexto")
        else:
            logger.warning(
                "Auto-promocao nao acionada — pre-condicoes: %s",
                "; ".join(erros_pre),
            )
            # Registrar erros no contexto para a LLM informar o cliente
            try:
                contexto_repo.registrar_fato(ContextoConversaCreate(
                    sessao_chat_id=sessao_id,
                    chave="erro_promocao",
                    valor_texto="; ".join(erros_pre),
                    valor_json=None,
                    tipo_de_verdade=TipoDeVerdade.validado_tool,
                    nivel_confirmacao=NivelConfirmacao.nenhum,
                    fonte=OrigemContexto.backend,
                ))
            except Exception:
                logger.exception("Falha ao registrar erro_promocao no contexto")

            # --- 12a. Auto-regressao: se erro e de estoque, regredir para oferta ---
            # Permite que o proximo turno busque alternativas em vez de ficar
            # preso em fechamento (estado que nao permite busca/oferta).
            _tem_erro_estoque = any("estoque" in e.lower() for e in erros_pre)
            if _tem_erro_estoque:
                logger.info("Auto-regressao: fechamento -> oferta (estoque insuficiente)")
                sessao_repo.atualizar_etapa(sessao_id, EtapaFluxo.oferta)

                # Cancelar itens provisorios sem estoque para evitar re-tentativa
                itens_ativos = item_provisorio_repo.listar_itens_ativos_por_sessao(sessao_id)
                for item in itens_ativos:
                    if item.pneu_id and any(str(item.pneu_id) in e for e in erros_pre):
                        item_provisorio_repo.atualizar_status_item(
                            item.id, StatusItemProvisorio.cancelado
                        )
                        logger.info(
                            "Item cancelado (estoque=0): %s (pneu_id=%s)",
                            item.id, item.pneu_id,
                        )

                # Limpar itens_finalizados para que a LLM possa adicionar novos
                contexto_repo.desativar_fato_anterior(sessao_id, "itens_finalizados")

    # --- 12b. Follow-up automatico quando frete foi calculado neste turno ---
    # O agente disse "Deixa eu verificar..." mas o backend ja resolveu.
    # Segunda chamada com contexto atualizado para informar o cliente sem
    # ele precisar enviar outra mensagem.
    envelope_pos_frete = None
    if (_frete_calculado_agora or _ambiguo_agora) and not pedido_criado:
        try:
            contexto_pos_frete = montar_contexto(sessao_id)
            if _ambiguo_agora:
                _TRIGGER_FRETE = (
                    "[SISTEMA] O bairro informado pelo cliente existe em mais de um municipio. "
                    "Veja o alerta 'MUNICIPIO AMBIGUO' no contexto. Voce DEVE perguntar ao cliente "
                    "em qual cidade/municipio ele mora. Nao diga 'verificar' nem 'aguarde'."
                )
            else:
                _TRIGGER_FRETE = (
                    "[SISTEMA] O frete para a localidade informada foi calculado automaticamente "
                    "neste turno. O valor ja esta no contexto (campo frete ou frete_nao_coberto). "
                    "Informe o cliente com o resultado e continue coletando os dados que faltam "
                    "(endereco completo, forma de pagamento). Nao diga 'verificar' nem 'aguarde'."
                )
            envelope_pos_frete, _ = _chamar_e_validar(contexto_pos_frete, _TRIGGER_FRETE)
            if envelope_pos_frete:
                logger.info("Follow-up frete: mensagem atualizada apos calculo automatico")
                # Processar fatos do follow-up (ex: municipio confirmado, entrega registrada)
                if envelope_pos_frete.fatos_observados:
                    _aplicar_fatos_observados(sessao_id, envelope_pos_frete.fatos_observados, msg_entrada.id)
                if envelope_pos_frete.fatos_inferidos:
                    _aplicar_fatos_inferidos(sessao_id, envelope_pos_frete.fatos_inferidos)
                if envelope_pos_frete.mudancas_contexto:
                    _aplicar_mudancas_contexto(sessao_id, envelope_pos_frete.mudancas_contexto)
        except Exception:
            logger.exception("Falha no follow-up de frete — usando mensagem original")

    # --- 13. Persistir mensagem de saida ---
    # Se um pedido foi criado neste turno, substituir a mensagem da IA
    # pela confirmacao formatada com dados reais do banco.
    # Se houve follow-up de frete, usar a mensagem do follow-up.
    mensagem_final = (
        _montar_confirmacao_pedido(pedido_criado)
        if pedido_criado
        else (envelope_pos_frete.mensagem_cliente if envelope_pos_frete else envelope.mensagem_cliente)
    )
    _persistir_saida(sessao_id, mensagem_final)

    # --- 14. Retornar mensagem + fotos (apenas se cliente solicitou) ---
    fotos_para_enviar: list[str] = []
    if _cliente_pediu_foto(mensagem_texto) and pneus_encontrados:
        fotos_para_enviar = [
            p["foto_url"]
            for p in pneus_encontrados
            if p.get("foto_url")
        ]
    return RespostaTurno(texto=mensagem_final, fotos=fotos_para_enviar)
