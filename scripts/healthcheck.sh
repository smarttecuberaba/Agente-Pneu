#!/bin/sh
# Health check usado pelo Docker/Coolify
curl -sf "http://localhost:${PORT:-8000}/health" || exit 1
