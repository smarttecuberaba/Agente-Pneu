#!/bin/sh
# Script de inicializacao do agente 2W Pneus
# Usado como entrypoint alternativo ao CMD do Dockerfile

set -e

echo "==================================================="
echo "  Agente 2W Pneus — iniciando"
echo "  PORT=${PORT:-8000}  LOG_LEVEL=${LOG_LEVEL:-info}"
echo "==================================================="

# Validar variaveis obrigatorias
: "${SUPABASE_URL:?SUPABASE_URL nao definida}"
: "${SUPABASE_KEY:?SUPABASE_KEY nao definida}"
: "${OPENAI_API_KEY:?OPENAI_API_KEY nao definida}"
: "${EVOLUTION_API_URL:?EVOLUTION_API_URL nao definida}"
: "${EVOLUTION_API_KEY:?EVOLUTION_API_KEY nao definida}"
: "${EVOLUTION_INSTANCE:?EVOLUTION_INSTANCE nao definida}"

exec uvicorn api.server:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --log-level "${LOG_LEVEL:-info}"
