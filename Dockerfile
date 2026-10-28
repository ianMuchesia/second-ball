# Second Ball, judge mode: the API serves one recorded run bundle and the built
# screen. It makes no model calls and needs no secrets.
#
#   docker build --build-arg RUN=demo-foundry-2 -t second-ball .
#   docker run -p 8000:8000 second-ball        # http://localhost:8000
#
# RUN is a bundle under runs/ (git-ignored: built from your local recording).
#
# Rebuilds stay quick: npm and uv keep their downloads in BuildKit cache mounts
# (on this machine, not in the image), so a step that reruns does not fetch the
# internet again, and a code change only copies code.

# ---- the screen ----------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --prefer-offline --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- the API ---------------------------------------------------------------------
FROM python:3.12-slim AS app
# Links the public GHCR package to the repository (infra/README.md).
LABEL org.opencontainers.image.source="https://github.com/ianMuchesia/second-ball"
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_HTTP_TIMEOUT=300
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
# The code is imported from /app, so the project itself is not installed: that
# step rebuilt the package and recompiled every dependency on each code change.
# Not evals/ or scripts/: recording and evaluation tools, not the site.
COPY core/ core/
COPY engine/ engine/
COPY stream/ stream/
COPY agents/ agents/
RUN python -m compileall -q core engine stream agents
COPY --from=web /web/dist web/dist

ARG RUN=demo-foundry-2
COPY runs/${RUN}/ runs/${RUN}/

# Public: reading only. Producer approve/reject and "inject a test error" are
# switched off (stream/api: PRODUCER_WRITES); no model is ever called.
ENV RUNS_DIR=/app/runs PRODUCER_WRITES=off PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app
RUN useradd --uid 10001 --no-create-home app && chown -R app /app/runs
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["uvicorn", "stream.api:app", "--host", "0.0.0.0", "--port", "8000"]
