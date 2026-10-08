FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f

WORKDIR /app
ARG SUPERCRONIC_VERSION=v0.2.49
ARG SUPERCRONIC_SHA256SUM_amd64=a53ae236602c7338aba3fbaff40bda6300eae3b9fedb8261eb06cfe3724430c1
ARG SUPERCRONIC_SHA256SUM_arm64=02aa0cb229ba09050cba6638059dadb9eedc2276632ea43d6a57a2f8c1629dd5
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -fsSLO "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}" \
    && case "${TARGETARCH}" in \
      amd64) EXPECTED="${SUPERCRONIC_SHA256SUM_amd64}" ;; \
      arm64) EXPECTED="${SUPERCRONIC_SHA256SUM_arm64}" ;; \
      *) echo 'unsupported TARGETARCH' >&2; exit 1 ;; \
    esac \
    && echo "${EXPECTED}  supercronic-linux-${TARGETARCH}" | sha256sum -c - \
    && chmod +x "supercronic-linux-${TARGETARCH}" \
    && mv "supercronic-linux-${TARGETARCH}" /usr/local/bin/supercronic \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt && python -m pip check

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} DRY_RUN=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY degiro_to_ghostfolio.py ghostfolio_core.py cash-rules.yaml entrypoint.sh ./
RUN chmod 755 /app/entrypoint.sh \
    && groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid appuser --no-create-home --system appuser
USER 10001:10001
ENTRYPOINT ["/app/entrypoint.sh"]
