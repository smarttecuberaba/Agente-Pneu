import logging
import os

import httpx
from supabase import create_client, Client
from supabase.lib.client_options import SyncClientOptions
from agente_2w.config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)


def _detectar_proxy() -> str | None:
    """Detecta proxy via env vars ou Windows Registry (apenas no Windows)."""
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if proxy:
        logger.debug("Proxy detectado via env: %s", proxy)
        return proxy
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                if enabled:
                    server, _ = winreg.QueryValueEx(key, "ProxyServer")
                    if server:
                        proxy = f"http://{server}" if not server.startswith("http") else server
                        logger.debug("Proxy detectado via Windows Registry: %s", proxy)
                        return proxy
        except Exception as e:
            logger.debug("Proxy Windows Registry nao disponivel: %s", e)
    return None


_proxy = _detectar_proxy()
_http_client = httpx.Client(proxy=_proxy) if _proxy else httpx.Client()

_options = SyncClientOptions(httpx_client=_http_client)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY, options=_options)
