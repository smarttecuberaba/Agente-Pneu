"""Servidor FastAPI — Agente 2W Pneus.

Endpoints:
  GET  /          — status do servidor
  GET  /health    — health check (usado pelo Coolify/Docker)
  POST /webhook   — recebe eventos do Chatwoot (mensagens WhatsApp via Baileys)

Fluxo:
  Cliente WhatsApp
    → Baileys (conector WhatsApp no Chatwoot)
    → Chatwoot (armazena conversa)
    → POST /webhook  (evento message_created, message_type=incoming)
    → processar_turno() do agente
    → Chatwoot API (envia resposta)
    → Baileys → Cliente WhatsApp
"""

import logging
import os
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from api.sessao_manager import obter_ou_criar_sessao
from api.chatwoot import enviar_mensagem

logger = logging.getLogger(__name__)

LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")


# ─────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Agente 2W Pneus iniciando...")
    yield
    logger.info("Agente 2W Pneus encerrando.")


app = FastAPI(
    title="Agente 2W Pneus",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)


# ─────────────────────────────────────────────────────────────
# Utilitarios
# ─────────────────────────────────────────────────────────────

def _normalizar_numero(telefone: str) -> str:
    """Remove '+', espacos e caracteres nao numericos do telefone."""
    return "".join(c for c in telefone if c.isdigit())


def _extrair_telefone(payload: dict) -> str | None:
    """Extrai o telefone do remetente do payload do Chatwoot.

    Chatwoot + Baileys coloca o numero em:
      conversation.meta.sender.phone_number  (formato: +5521999999999)
    """
    try:
        telefone = (
            payload
            .get("conversation", {})
            .get("meta", {})
            .get("sender", {})
            .get("phone_number", "")
        )
        if telefone:
            return _normalizar_numero(telefone)
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────
# Processamento em background
# ─────────────────────────────────────────────────────────────

async def _processar_mensagem(
    contato: str,
    texto: str,
    conversation_id: int,
    message_id: int | None,
):
    """Processa turno do agente e envia resposta via Chatwoot."""
    from agente_2w.engine.orquestrador import processar_turno

    try:
        sessao_id = obter_ou_criar_sessao(contato)
        logger.info(
            "Processando turno | contato=%s sessao=%s conversa_cw=#%d",
            contato, sessao_id, conversation_id,
        )

        # processar_turno e sincrono — roda em thread separada
        loop = asyncio.get_event_loop()
        resposta = await loop.run_in_executor(
            None,
            lambda: processar_turno(
                sessao_id,
                texto,
                message_id_externo=str(message_id) if message_id else None,
            ),
        )

        await enviar_mensagem(conversation_id, resposta)
        logger.info("Resposta enviada para conversa #%d (%d chars)", conversation_id, len(resposta))

    except Exception as e:
        logger.error(
            "Erro ao processar mensagem da conversa #%d: %s",
            conversation_id, e, exc_info=True,
        )
        # Falha segura: tenta avisar o cliente
        try:
            await enviar_mensagem(
                conversation_id,
                "Desculpe, tive um problema ao processar sua mensagem. Pode repetir?",
            )
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# Rotas
# ─────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "online", "servico": "Agente 2W Pneus"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    """Recebe eventos do Chatwoot.

    O Chatwoot envia um POST para esta rota a cada evento configurado.
    So processamos mensagens recebidas do cliente (message_type=incoming).

    Payload esperado (event: message_created):
    {
      "event": "message_created",
      "id": 42,
      "content": "oi, preciso de um pneu",
      "message_type": "incoming",
      "content_type": "text",
      "conversation": {
        "id": 123,
        "meta": {
          "sender": {
            "name": "Joao",
            "phone_number": "+5521999999999"
          }
        }
      },
      "account": {"id": 1}
    }
    """
    # Validacao do segredo via query param: /webhook?secret=XXX
    secret = request.query_params.get("secret") or request.headers.get("x-webhook-secret")
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        logger.warning("Webhook recebido com segredo invalido (ip=%s)", request.client.host)
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalido")

    event = payload.get("event", "")

    # So processa criacao de mensagens
    if event != "message_created":
        return JSONResponse({"ok": True, "ignorado": event})

    # So processa mensagens recebidas do cliente (nao as enviadas pelo bot)
    message_type = payload.get("message_type", "")
    if message_type != "incoming":
        return JSONResponse({"ok": True, "ignorado": f"message_type={message_type}"})

    # Ignorar mensagens sem texto (audio, imagem sem legenda, etc.)
    content_type = payload.get("content_type", "")
    if content_type != "text":
        logger.debug("Mensagem ignorada: content_type=%s", content_type)
        return JSONResponse({"ok": True, "ignorado": f"content_type={content_type}"})

    texto = (payload.get("content") or "").strip()
    if not texto:
        return JSONResponse({"ok": True, "ignorado": "sem_texto"})

    # Extrair conversation_id (obrigatorio para responder)
    conversation_id = payload.get("conversation", {}).get("id")
    if not conversation_id:
        logger.warning("Webhook sem conversation.id")
        return JSONResponse({"ok": True, "ignorado": "sem_conversation_id"})

    # Extrair telefone do remetente
    contato = _extrair_telefone(payload)
    if not contato:
        logger.warning("Webhook sem telefone do remetente (conversa #%s)", conversation_id)
        return JSONResponse({"ok": True, "ignorado": "sem_telefone"})

    message_id = payload.get("id")

    logger.info(
        "Mensagem recebida | conversa=#%d contato=%s texto='%s...'",
        conversation_id, contato, texto[:40],
    )

    # Processar em background — responde o webhook imediatamente
    background_tasks.add_task(
        _processar_mensagem,
        contato,
        texto,
        conversation_id,
        message_id,
    )

    return JSONResponse({"ok": True})
