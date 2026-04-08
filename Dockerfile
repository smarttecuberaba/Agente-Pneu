FROM python:3.12-slim

WORKDIR /app

# Dependencias do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencias Python (cache de layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Codigo do projeto
COPY agente_2w/ ./agente_2w/
COPY webhook_server.py .

EXPOSE 5002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:5002/health || exit 1

CMD ["uvicorn", "webhook_server:app", "--host", "0.0.0.0", "--port", "5002", "--workers", "1"]
