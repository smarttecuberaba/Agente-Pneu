"""Webhook server — ponte entre Chatwoot/WhatsApp e o agente 2W Pneus.

Endpoints:
    GET  /health          -> health check para Coolify (valida Supabase)
    POST /webhook/chatwoot -> recebe eventos do Chatwoot
"""

import asyncio
import hashlib
import hmac
import logging
import os
import re
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from threading import Lock

import tempfile

import httpx
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from openai import OpenAI

from agente_2w.config import SUPABASE_URL, OPENAI_MODEL, OPENAI_API_KEY
from agente_2w.db import sessao_repo
from agente_2w.engine.orquestrador import processar_turno, MENSAGEM_FALHA_SEGURA
from agente_2w.enums.enums import EtapaFluxo, StatusSessao
from agente_2w.schemas.sessao_chat import SessaoChatCreate

# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("webhook")

CHATWOOT_BASE_URL = os.environ["CHATWOOT_BASE_URL"].rstrip("/")
CHATWOOT_API_TOKEN = os.environ["CHATWOOT_API_TOKEN"]
CHATWOOT_ACCOUNT_ID = os.environ["CHATWOOT_ACCOUNT_ID"]
CHATWOOT_INBOX_ID = os.getenv("CHATWOOT_INBOX_ID")
CHATWOOT_WEBHOOK_SECRET = os.getenv("CHATWOOT_WEBHOOK_SECRET", "")

# ---------------------------------------------------------------------------
# Dedup thread-safe (LRU)
# ---------------------------------------------------------------------------

_MAX_CACHE = 5000
_cache_lock = Lock()
_mensagens_processadas: OrderedDict[str, bool] = OrderedDict()


def _mensagem_ja_processada(message_id: str) -> bool:
    """Verifica e registra message_id de forma thread-safe."""
    if not message_id:
        return False
    with _cache_lock:
        if message_id in _mensagens_processadas:
            return True
        _mensagens_processadas[message_id] = True
        while len(_mensagens_processadas) > _MAX_CACHE:
            _mensagens_processadas.popitem(last=False)
    return False


# ---------------------------------------------------------------------------
# Lock por telefone (evita sessao duplicada)
# ---------------------------------------------------------------------------

_sessao_locks: dict[str, Lock] = {}
_sessao_locks_lock = Lock()


def _lock_para_telefone(telefone: str) -> Lock:
    with _sessao_locks_lock:
        if telefone not in _sessao_locks:
            _sessao_locks[telefone] = Lock()
        return _sessao_locks[telefone]


# ---------------------------------------------------------------------------
# HTTP client (ciclo de vida correto via lifespan)
# ---------------------------------------------------------------------------

_http: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http
    _http = httpx.AsyncClient(timeout=30.0)
    logger.info("Agente 2W Pneus webhook iniciado")
    logger.info("  Chatwoot:    %s", CHATWOOT_BASE_URL)
    logger.info("  Account ID:  %s", CHATWOOT_ACCOUNT_ID)
    logger.info("  Supabase:    %s...", SUPABASE_URL[:40])
    logger.info("  Modelo:      %s", OPENAI_MODEL)
    yield
    await _http.aclose()
    logger.info("Webhook encerrado")


app = FastAPI(title="Agente 2W Pneus - Webhook", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalizar_telefone(raw: str) -> str:
    """Extrai apenas digitos do telefone. Garante formato 55XXXXXXXXXXX."""
    digitos = re.sub(r"\D", "", raw or "")
    if digitos and not digitos.startswith("55"):
        digitos = "55" + digitos
    return digitos


def _extrair_telefone_do_identifier(identifier: str) -> str:
    """Extrai telefone do identifier do Baileys.

    Baileys envia '5534999999999@s.whatsapp.net' — extrai so o numero.
    """
    if not identifier:
        return ""
    return identifier.split("@")[0]


def _verificar_assinatura(body: bytes, signature: str) -> bool:
    """Valida HMAC-SHA256 do webhook (se secret configurado)."""
    if not CHATWOOT_WEBHOOK_SECRET:
        return True
    expected = hmac.new(
        CHATWOOT_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _obter_ou_criar_sessao(telefone: str) -> object:
    """Busca sessao ativa pelo telefone ou cria nova (thread-safe).

    Retorna o objeto SessaoChat completo para acesso a .id e outros campos.
    """
    lock = _lock_para_telefone(telefone)
    with lock:
        sessao = sessao_repo.buscar_sessao_ativa_por_contato(telefone)
        if sessao:
            logger.debug(
                "Sessao existente: %s (etapa=%s)",
                sessao.id, sessao.etapa_atual.value,
            )
            return sessao

        sessao = sessao_repo.criar_sessao(SessaoChatCreate(
            canal="whatsapp",
            contato_externo=telefone,
            etapa_atual=EtapaFluxo.identificacao,
            status_sessao=StatusSessao.ativa,
        ))
        logger.info("Nova sessao criada: %s para %s", sessao.id, telefone)
        return sessao


async def _enviar_mensagem_chatwoot(conversation_id: int, texto: str) -> None:
    """Envia mensagem de resposta via API do Chatwoot."""
    url = (
        f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}"
        f"/conversations/{conversation_id}/messages"
    )
    headers = {"api_access_token": CHATWOOT_API_TOKEN}
    payload = {
        "content": texto,
        "message_type": "outgoing",
        "private": False,
    }
    try:
        resp = await _http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        logger.info(
            "Resposta enviada: conv=%s (%d chars)", conversation_id, len(texto),
        )
    except httpx.HTTPStatusError as e:
        logger.error(
            "Erro ao enviar para Chatwoot: %s - %s",
            e.response.status_code, e.response.text,
        )
    except Exception as e:
        logger.error("Erro de conexao com Chatwoot: %s", e)


async def _enviar_foto_chatwoot(conversation_id: int, foto_url: str) -> None:
    """Envia foto como mensagem no Chatwoot (URL como texto)."""
    await _enviar_mensagem_chatwoot(conversation_id, foto_url)


# ---------------------------------------------------------------------------
# Transcricao de audio (Whisper / OpenAI)
# ---------------------------------------------------------------------------

_openai_client = OpenAI(api_key=OPENAI_API_KEY, timeout=60)


async def _transcrever_audio(audio_url: str) -> str:
    """Baixa audio pela URL e transcreve via Whisper da OpenAI.

    Retorna o texto transcrito ou string vazia se falhar.
    """
    try:
        resp = await _http.get(audio_url, timeout=30.0)
        resp.raise_for_status()
    except Exception as e:
        logger.error("Falha ao baixar audio: %s", e)
        return ""

    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            transcricao = await asyncio.to_thread(
                lambda: _openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="pt",
                )
            )

        os.unlink(tmp_path)
        texto = transcricao.text.strip()
        logger.info("Audio transcrito (%d chars): '%s'", len(texto), texto[:80])
        return texto

    except Exception as e:
        logger.error("Falha ao transcrever audio: %s", e)
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Health check com validacao de conectividade Supabase."""
    try:
        from agente_2w.db.client import supabase
        supabase.table("sessao_chat").select("id").limit(1).execute()
        return {"status": "ok", "service": "agente-2w-pneus"}
    except Exception as e:
        logger.error("Health check falhou: %s", e)
        raise HTTPException(status_code=503, detail="Supabase indisponivel")


@app.post("/webhook/chatwoot")
async def chatwoot_webhook(request: Request, background_tasks: BackgroundTasks):
    """Recebe webhooks do Chatwoot (evento message_created)."""

    # 1. Validar assinatura HMAC
    body = await request.body()
    signature = request.headers.get("x-chatwoot-signature", "")
    if CHATWOOT_WEBHOOK_SECRET and not _verificar_assinatura(body, signature):
        logger.warning("Assinatura invalida no webhook")
        raise HTTPException(status_code=401, detail="Assinatura invalida")

    data = await request.json()

    # 2. Filtrar: so processar message_created
    event = data.get("event")
    if event != "message_created":
        return {"status": "ignored", "event": event}

    # 3. Filtrar: so processar mensagens incoming (do cliente)
    message_type = data.get("message_type")
    if message_type not in (0, "incoming"):
        return {"status": "ignored", "reason": "not_incoming"}

    # 4. Ignorar mensagens privadas (notas internas)
    if data.get("private", False):
        return {"status": "ignored", "reason": "private"}

    # 5. Extrair dados basicos
    content = (data.get("content") or "").strip()
    conversation = data.get("conversation", {})
    conversation_id = conversation.get("id")
    inbox_id = conversation.get("inbox_id")
    sender = data.get("sender", {})
    sender_meta = conversation.get("meta", {}).get("sender", {})

    # 6. Gerar message_id robusto
    raw_id = data.get("id")
    message_id = (
        str(raw_id) if raw_id
        else f"cw_{conversation_id}_{datetime.now(timezone.utc).timestamp()}"
    )

    # 7. Filtrar por inbox (opcional)
    if CHATWOOT_INBOX_ID and str(inbox_id) != str(CHATWOOT_INBOX_ID):
        return {"status": "ignored", "reason": "wrong_inbox"}

    # 8. Extrair telefone — varios locais possiveis
    telefone_raw = (
        sender.get("phone_number")
        or sender_meta.get("phone_number")
        or _extrair_telefone_do_identifier(sender.get("identifier", ""))
        or _extrair_telefone_do_identifier(sender_meta.get("identifier", ""))
        or conversation.get("contact", {}).get("phone_number")
        or ""
    )
    telefone = _normalizar_telefone(telefone_raw)

    if not telefone:
        telefone = f"chatwoot_{conversation_id}"
        logger.warning("Telefone nao encontrado, usando fallback: %s", telefone)

    # 9. Dedup
    if _mensagem_ja_processada(message_id):
        return {"status": "ignored", "reason": "duplicate"}

    # 10. Extrair imagens e audios dos attachments
    attachments = data.get("attachments") or []
    imagens = [
        a.get("data_url") or a.get("url", "")
        for a in attachments
        if a.get("file_type") == "image"
    ]
    imagens = [u for u in imagens if u]

    audios = [
        a.get("data_url") or a.get("url", "")
        for a in attachments
        if a.get("file_type") == "audio"
    ]
    audios = [u for u in audios if u]

    # 11. Texto vazio sem imagens e sem audios — pedir descricao
    if not content and not imagens and not audios:
        content = "Recebi seu arquivo! Pode descrever o que precisa?"

    logger.info(
        "Mensagem recebida: conv=%s tel=%s msg_id=%s texto='%s' imagens=%d audios=%d",
        conversation_id, telefone, message_id, content[:80], len(imagens), len(audios),
    )

    # 12. Processar em background — retorna 200 imediato pro Chatwoot
    async def _processar_e_responder():
        nonlocal content
        try:
            # 12a. Transcrever audios (se houver)
            for audio_url in audios:
                texto_audio = await _transcrever_audio(audio_url)
                if texto_audio:
                    content = f"{content} {texto_audio}".strip() if content else texto_audio

            sessao = await asyncio.to_thread(_obter_ou_criar_sessao, telefone)

            resposta = await asyncio.to_thread(
                processar_turno,
                sessao.id,
                content,
                message_id_externo=message_id,
                imagens=imagens or None,
            )

            # Enviar texto
            if resposta.texto:
                await _enviar_mensagem_chatwoot(conversation_id, resposta.texto)

            # Enviar fotos
            for foto_url in resposta.fotos or []:
                await _enviar_foto_chatwoot(conversation_id, foto_url)

        except Exception as e:
            logger.error("Erro ao processar mensagem: %s", e, exc_info=True)
            await _enviar_mensagem_chatwoot(conversation_id, MENSAGEM_FALHA_SEGURA)

    background_tasks.add_task(_processar_e_responder)

    return {"status": "processing", "message_id": message_id}
