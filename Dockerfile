FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

WORKDIR /app
ARG SUPERCRONIC_VERSION=v0.2.49
ARG SUPERCRONIC_SHA256SUM_amd64=a53ae236602c7338aba3fbaff40bda6300eae3b9fedb8261eb06cfe3724430c1
ARG SUPERCRONIC_SHA256SUM_arm64=02aa0cb229ba09050cba6638059dadb9eedc2276632ea43d6a57a2f8c1629dd5
ARG TARGETARCH
ARG BW_VERSION=2026.9.1
ARG BW_SHA256SUM_amd64=b90c0fc86bcf11c0b194aa3f0a89344738af0512cb267c39ad3250c5edd71663
ARG BW_SHA256SUM_arm64=6c2765f91d5bbba9864195c9a304a683bcc0bfa39cfd85ce9423142631e111a6
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip tzdata libstdc++6 \
    && curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSLO "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}" \
    && case "${TARGETARCH}" in \
      amd64) EXPECTED="${SUPERCRONIC_SHA256SUM_amd64}" ;; \
      arm64) EXPECTED="${SUPERCRONIC_SHA256SUM_arm64}" ;; \
      *) echo 'unsupported TARGETARCH' >&2; exit 1 ;; \
    esac \
    && echo "${EXPECTED}  supercronic-linux-${TARGETARCH}" | sha256sum -c - \
    && chmod +x "supercronic-linux-${TARGETARCH}" \
    && mv "supercronic-linux-${TARGETARCH}" /usr/local/bin/supercronic \
    && case "${TARGETARCH}" in \
      amd64) BW_PLATFORM=linux; BW_EXPECTED="${BW_SHA256SUM_amd64}" ;; \
      arm64) BW_PLATFORM=linux-arm64; BW_EXPECTED="${BW_SHA256SUM_arm64}" ;; \
    esac \
    && curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL "https://github.com/bitwarden/clients/releases/download/cli-v${BW_VERSION}/bw-oss-${BW_PLATFORM}-${BW_VERSION}.zip" -o /tmp/bw.zip \
    && echo "${BW_EXPECTED}  /tmp/bw.zip" | sha256sum -c - \
    && unzip /tmp/bw.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/bw \
    && bw --version \
    && rm /tmp/bw.zip \
    && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# pip is build-time only; remove its unused vendored dependencies from runtime.
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip check \
    && python -m pip uninstall -y pip

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} DRY_RUN=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY degiro_to_ghostfolio.py ghostfolio_core.py cash-rules.yaml entrypoint.sh ./
COPY scripts/recover_degiro.py ./scripts/recover_degiro.py
COPY scripts/check_scheduler.py ./scripts/check_scheduler.py
COPY third_party/bitwarden/ /usr/local/share/bitwarden/
RUN chmod 755 /app/entrypoint.sh \
    && groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid appuser --no-create-home --system appuser
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD ["python", "/app/scripts/check_scheduler.py"]
ENTRYPOINT ["/app/entrypoint.sh"]
