# ==============================================================================
# Forsis AI Agent — Python 3.12 + FastAPI Runtime
# Base: python:3.12-slim (Debian bookworm, menor superficie de ataque que Alpine)
# Justificación: psycopg2-binary y PyMySQL tienen mejor soporte en glibc que musl
# ==============================================================================
FROM python:3.12-slim AS base

# Paquetes del sistema (PostgreSQL client libs, MySQL client, curl para health)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    default-libmysqlclient-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Usuario no-root para runtime
RUN useradd -m -u 1000 -s /bin/bash agentuser

WORKDIR /app

# --- Build stage: instalar dependencias ---
FROM base AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# --- Runtime stage: imagen final ---
FROM base

# Copiar dependencias instaladas desde el build stage
COPY --from=builder /root/.local /home/agentuser/.local
ENV PATH=/home/agentuser/.local/bin:$PATH

# Copiar código de aplicación
# NOTA: ./knowledge NO se copia a la imagen a propósito (ver architecture-python.md §9.1).
# Es documentación interna de análisis (~764 KB) que incluye hallazgos de seguridad de los
# sistemas de la empresa; ningún módulo de app/ la lee en runtime. El compose la monta
# como bind-mount read-only (./knowledge:/app/knowledge:ro) cuando se necesite para RAG,
# lo que además hacía que esta capa de la imagen quedara shadowed e inútil.
COPY --chown=agentuser:agentuser ./app /app/app

# Punto de entrada
COPY docker/app/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER agentuser

# Health check endpoint (FastAPI on :8000)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=40s \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--log-level", "info"]
