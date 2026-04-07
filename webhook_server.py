"""Webhook server — ponte entre Chatwoot/WhatsApp e o agente 2W Pneus.

Endpoints:
    GET  /health   -> health check para Coolify
    POST /webhook  -> recebe eventos do Chatwoot
"""

import asyncio
import hashlib
import hmac
import logging
import os
from collections import OrderedDict
from functools import partial

import httpx
from fastapi import FastAPI, Request, Response

from agente_2w.db import sessao_repo
from agente_2w.engine.orquestrador import processar_turno
from agente_2w.enums.enums import EtapaFluxo, StatusSessao
from agente_2w.schemas.sessao_chat import SessaoChatCreate

# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("webhook")

CHATWOOT_BASE_URL = os.environ["CHATWOOT_BASE_URL"]
CHATWOOT_API_TOKEN = os.environ["CHATWOOT_API_TOKEN"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

app = FastAPI(title="2W Pneus Webhook", docs_url=None, redoc_url=None)

# Cliente HTTP reutilizavel para chamadas ao Chatwoot
_http = httpx.AsyncClient(timeout=30.0)

# ---------------------------------------------------------------------------
# Fila por telefone — serializa mensagens do mesmo cliente
# ---------------------------------------------------------------------------

_filas: dict[str, asyncio.Lock] = {}
_filas_lock = asyncio.Lock()


async def _get_fila(telefone: str) -> asyncio.Lock:
    async with _filas_lock:
        if telefone not in _filas:
            _filas[telefone] = asyncio.Lock()
        return _filas[telefone]


# ---------------------------------------------------------------------------
# Dedup em memoria — evita processar a mesma mensagem 2x (retry do Chatwoot)
# ---------------------------------------------------------------------------

_MAX_IDS = 10_000
_ids_processados: OrderedDict[str, None] = OrderedDict()


def _ja_processado(message_id: str) -> bool:
    if message_id in _ids_processados:
        return True
    _ids_processados[message_id] = None
    # Evicta os mais antigos quando ultrapassa o limite
    while len(_ids_processados) > _MAX_IDS:
        _ids_processados.popitem(last=False)
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalizar_telefone(raw: str) -> str:
    """Remove '+' e espacos para casar com contato_externo do banco.

    Chatwoot envia '+5521999999999', o CLI salva '5521999999999'.
    """
    return raw.replace("+", "").replace(" ", "").strip()


def _validar_hmac(body: bytes, signature: str) -> bool:
    """Valida X-Chatwoot-Signature via HMAC-SHA256."""
    if not WEBHOOK_SECRET:
        return True  # sem secret configurado, aceita tudo (dev)
    expected = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _enviar_mensagem_chatwoot(
    account_id: int,
    conversation_id: int,
    texto: str,
) -> None:
    """Envia mensagem de resposta via API REST do Chatwoot."""
    url = (
        f"{CHATWOOT_BASE_URL}/api/v1/accounts/{account_id}"
        f"/conversations/{conversation_id}/messages"
    )
    headers = {"api_access_token": CHATWOOT_API_TOKEN}
    payload = {
        "content": texto,
        "message_type": "outgoing",
        "private": False,
    }
    resp = await _http.post(url, json=payload, headers=headers)
    resp.raise_for_status()


async def _enviar_foto_chatwoot(
    account_id: int,
    conversation_id: int,
    foto_url: str,
) -> None:
    """Envia foto como mensagem no Chatwoot.

    V1: envia a URL como texto. O Chatwoot renderiza como link clicavel.
    TODO V2: baixar a imagem e enviar como attachment multipart.
    """
    await _enviar_mensagem_chatwoot(account_id, conversation_id, foto_url)


def _buscar_ou_criar_sessao(telefone: str):
    """Busca sessao ativa ou cria nova. Funcao SINCRONA (roda em executor)."""
    sessao = sessao_repo.buscar_sessao_ativa_por_contato(telefone)
    if sessao is None:
        sessao = sessao_repo.criar_sessao(SessaoChatCreate(
            canal="whatsapp",
            contato_externo=telefone,
            etapa_atual=EtapaFluxo.identificacao,
            status_sessao=StatusSessao.ativa,
        ))
        logger.info("Nova sessao criada: %s para %s", sessao.id, telefone)
    return sessao


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.body()

    # 1. Validar HMAC
    signature = request.headers.get("X-Chatwoot-Signature", "")
    if not _validar_hmac(body, signature):
        logger.warning("HMAC invalido — request rejeitado")
        return Response(status_code=403)

    try:
        payload = await request.json()
    except Exception:
        logger.warning("Payload nao e JSON valido")
        return Response(status_code=200)

    # 2. Filtrar eventos irrelevantes
    event = payload.get("event")
    message_type = payload.get("message_type")
    if event != "message_created" or message_type != "incoming":
        return Response(status_code=200)

    # 3. Ignorar mensagens do proprio agente/bot
    sender = payload.get("sender") or {}
    if sender.get("type") != "contact":
        return Response(status_code=200)

    # 4. Extrair dados do payload
    conversation = payload.get("conversation") or {}
    meta = conversation.get("meta") or {}
    sender_meta = meta.get("sender") or {}
    account = payload.get("account") or {}

    telefone_raw = sender_meta.get("phone_number", "")
    telefone = _normalizar_telefone(telefone_raw)
    if not telefone:
        logger.warning("Mensagem sem telefone — ignorando")
        return Response(status_code=200)

    texto = payload.get("content") or ""
    message_id = str(payload.get("id", ""))
    account_id = account.get("id")
    conversation_id = conversation.get("id")

    # Extrair imagens dos attachments
    attachments = payload.get("attachments") or []
    imagens = [
        a["data_url"] if "data_url" in a else a.get("url", "")
        for a in attachments
        if a.get("file_type") == "image"
    ]
    imagens = [u for u in imagens if u]  # remover vazios

    # 5. Dedup
    if message_id and _ja_processado(message_id):
        logger.info("Mensagem %s ja processada — ignorando", message_id)
        return Response(status_code=200)

    # 6. Fila por telefone
    lock = await _get_fila(telefone)
    async with lock:
        try:
            loop = asyncio.get_event_loop()

            # 7. Buscar/criar sessao (sync -> executor)
            sessao = await loop.run_in_executor(
                None, partial(_buscar_ou_criar_sessao, telefone)
            )

            # 8. Texto vazio sem imagens
            if not texto.strip() and not imagens:
                texto = "Recebi seu arquivo! Pode descrever o que precisa?"

            # 9. Processar turno (sync -> executor)
            logger.info(
                "Processando: tel=%s sessao=%s texto='%s' imagens=%d",
                telefone, sessao.id, texto[:80], len(imagens),
            )
            resposta = await loop.run_in_executor(
                None,
                partial(
                    processar_turno,
                    sessao.id,
                    texto,
                    message_id_externo=message_id or None,
                    imagens=imagens or None,
                ),
            )

            # 10. Enviar resposta de texto
            if resposta.texto and account_id and conversation_id:
                await _enviar_mensagem_chatwoot(
                    account_id, conversation_id, resposta.texto
                )

            # 11. Enviar fotos (se houver)
            for foto_url in resposta.fotos or []:
                await _enviar_foto_chatwoot(
                    account_id, conversation_id, foto_url
                )

        except Exception:
            logger.exception(
                "Erro ao processar mensagem de %s (msg_id=%s)",
                telefone, message_id,
            )

    # 12. Sempre retornar 200 — evitar retry do Chatwoot
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------

@app.on_event("shutdown")
async def shutdown():
    await _http.aclose()
