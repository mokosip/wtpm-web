FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen

ENV HOST=0.0.0.0 PORT=8000 PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
USER nobody
CMD ["python", "-m", "wtpm.server"]
