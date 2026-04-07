import os
from dotenv import load_dotenv

load_dotenv(override=True)

SUPABASE_URL: str = os.environ["SUPABASE_URL"]
SUPABASE_KEY: str = os.environ["SUPABASE_KEY"]

OPENAI_API_KEY: str = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")

# ─── Limites de execucao ──────────────────────────────────────────────────────
# Quantos retries a IA ganha quando o envelope vem invalido
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "2"))

# Quantos rounds de tool calls a IA pode fazer em um unico turno
MAX_TOOL_ROUNDS: int = int(os.getenv("MAX_TOOL_ROUNDS", "5"))
