# syntax=docker/dockerfile:1.7
# Multi-stage image for the Linux on-prem deployment: node builds the console,
# python installs the Crosscut packages and serves as the shared runtime image
# for the api, runtime and gateway containers. See deploy/docker/README.md.

FROM node:22.11.0-bookworm-slim@sha256:f035ba7ffee18f67200e2eb8018e0f13c954ec16338f264940f701997e3c12da AS frontend-build
WORKDIR /build/frontend
# Install from the lock file first so a source-only change reuses this layer.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12.7-slim-bookworm@sha256:60d9996b6a8a3689d36db740b49f4327be3be09a21122bd02fb8895abb38b50d AS python-runtime
# Unbuffered output reaches `docker compose logs` immediately; the schema folder
# is fixed here because the API and runtime resolve contracts from it.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CROSSCUT_SCHEMAS_DIR=/opt/crosscut/schemas
WORKDIR /opt/crosscut

# Two unprivileged accounts share one group: the API signs gateway commands and
# reads the 0640 key, the gateway owns its policy and mailbox volume.
RUN groupadd --gid 10000 crosscut-sec \
 && useradd --uid 10001 --gid crosscut-sec --home-dir /nonexistent \
      --no-create-home --shell /usr/sbin/nologin crosscut-api \
 && useradd --uid 10002 --gid crosscut-sec --home-dir /nonexistent \
      --no-create-home --shell /usr/sbin/nologin crosscut-gw

# Editable installs keep the package paths under /opt/crosscut, which is how the
# gateway finds schemas/ by walking up from crosscut_gateway/ (see policy_file).
COPY sim ./sim
COPY artifacts ./artifacts
COPY connectors ./connectors
COPY loops ./loops
COPY fuzzy ./fuzzy
COPY supervisor ./supervisor
COPY anomaly ./anomaly
COPY softsensor ./softsensor
COPY opcua ./opcua
COPY gateway ./gateway
COPY runtime ./runtime
COPY api ./api
COPY schemas ./schemas
COPY deploy/docker ./deploy/docker
COPY deploy/examples ./deploy/examples
RUN pip install --no-cache-dir --upgrade pip==24.3.1 \
 && pip install --no-cache-dir \
      -e ./sim -e ./artifacts -e ./connectors -e ./loops -e ./fuzzy \
      -e ./supervisor -e ./anomaly -e ./softsensor -e ./opcua \
      -e ./gateway -e ./runtime -e ./api \
      "uvicorn==0.32.0" "asyncua==2.1.0"

COPY --from=frontend-build /build/frontend/dist /opt/crosscut/frontend/dist

# Volume seed: Docker copies this ownership into an empty named volume. The data
# root belongs to the API account; the gateway folder belongs to the gateway.
RUN install -d -o crosscut-api -g crosscut-sec -m 0770 /var/lib/crosscut \
 && install -d -o crosscut-gw -g crosscut-sec -m 0770 /var/lib/crosscut/_gateway \
 && install -d -o crosscut-gw -g crosscut-sec -m 0770 \
      /var/lib/crosscut/_gateway/inbox \
      /var/lib/crosscut/_gateway/outbox \
      /var/lib/crosscut/_gateway/rejected \
      /var/lib/crosscut/_gateway/policy \
 && install -d -o crosscut-api -g crosscut-sec -m 0750 /var/lib/crosscut/_gateway/secrets

# Never start as root, even if a compose file forgets to set `user`.
USER crosscut-api
EXPOSE 8000
CMD ["python", "/opt/crosscut/deploy/docker/api_entrypoint.py"]
