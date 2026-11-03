# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.13-slim-bookworm
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_URL=sqlite:////data/dashboard.db PORT=8000
RUN useradd --system --uid 10001 --create-home app && mkdir /data && chown app:app /data
WORKDIR /app
COPY --from=build /app /app
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8000'))" || exit 1
CMD ["sh", "-c", "exec gunicorn 'google_ads_dashboard.app:create_app()' --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY:-2} --access-logfile -"]
