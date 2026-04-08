"""Cliente HTTP para envio de mensagens via API do Chatwoot.

O Chatwoot recebe a mensagem do cliente via Baileys (WhatsApp),
nos processamos com o agente e respondemos pela API do Chatwoot,
que repassa ao cliente via WhatsApp.

Referencia:
  POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/messages
"""

import logging
import os
import httpx

logger = logging.getLogger(__name__)

CHATWOOT_URL      = os.getenv("CHATWOOT_URL", "https://chatwoot.smarttecsolutions.com.br").rstrip("/")
CHATWOOT_TOKEN    = os.getenv("CHATWOOT_API_TOKEN", "")
CHATWOOT_ACCOUNT  = os.getenv("CHATWOOT_ACCOUNT_ID", "1")

_HEADERS = {
    "Content-Type": "application/json",
    "api_access_token": CHATWOOT_TOKEN,
}


async def enviar_mensagem(conversation_id: int, texto: str) -> bool:
    """Envia mensagem de saida para uma conversa no Chatwoot.

    O Chatwoot repassa ao cliente via WhatsApp (Baileys).
    Retorna True se enviou, False se falhou.
    """
    if not CHATWOOT_TOKEN:
        logger.error("CHATWOOT_API_TOKEN nao configurado")
        return False

    url = f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT}/conversations/{conversation_id}/messages"
    payload = {
        "content": texto,
        "message_type": "outgoing",
        "private": False,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=_HEADERS)
            resp.raise_for_status()
            logger.info("Mensagem enviada para conversa #%d (%d chars)", conversation_id, len(texto))
            return True
    except httpx.HTTPStatusError as e:
        logger.error(
            "Chatwoot erro %d ao enviar para conversa #%d: %s",
            e.response.status_code, conversation_id, e.response.text,
        )
        return False
    except Exception as e:
        logger.error("Falha ao enviar mensagem para conversa #%d: %s", conversation_id, e)
        return False
