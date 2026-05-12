FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

WORKDIR /app

COPY mcp-server/pyproject.toml /app/mcp-server/pyproject.toml
COPY mcp-server/mcp_server /app/mcp-server/mcp_server

RUN python -m pip install --upgrade pip \
    && python -m pip install /app/mcp-server \
    && adduser --disabled-password --gecos "" appuser

USER appuser

EXPOSE 8000

ENTRYPOINT ["mcp-server-elk"]
CMD ["--mode", "kibana", "--transport", "sse", "--host", "0.0.0.0", "--port", "8000", "--timeout", "30s", "--max-results", "50", "--max-time-range", "7d", "--verify-certs", "true"]
