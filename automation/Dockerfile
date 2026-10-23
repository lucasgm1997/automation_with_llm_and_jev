# syntax=docker/dockerfile:1
FROM dart:3.10.4-sdk AS marionette
WORKDIR /build/marionette
COPY automation/docker/marionette/pubspec.* ./
RUN dart pub get --enforce-lockfile
COPY automation/docker/marionette/bin ./bin
RUN dart compile exe bin/main.dart -o /build/marionette_mcp

FROM ghcr.io/astral-sh/uv:0.9.21 AS uv
FROM python:3.11.14-slim-trixie AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app/automation
ENV UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/automation/.venv/bin:$PATH" \
    MARIONETTE_BIN=/usr/local/bin/marionette_mcp \
    JEV_ANDROID_PREPARE_ENABLED=0
COPY automation/pyproject.toml automation/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache --extra android
COPY --from=marionette /build/marionette_mcp /usr/local/bin/marionette_mcp
COPY automation/jev_e2e ./jev_e2e
COPY automation/examples ./examples
RUN mkdir -p artifacts && chown 1000:1000 artifacts
USER 1000:1000
EXPOSE 8765
ENTRYPOINT ["python", "-m", "jev_e2e"]
CMD ["serve", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8765"]
