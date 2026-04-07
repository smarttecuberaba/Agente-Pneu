FROM python:3.11-slim

WORKDIR /app

# Dependencias primeiro (cache de layer do Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Codigo do projeto
COPY agente_2w/ ./agente_2w/
COPY webhook_server.py .

EXPOSE 8000

CMD ["uvicorn", "webhook_server:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "65"]
