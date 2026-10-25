FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

WORKDIR /app
ARG SUPERCRONIC_VERSION=v0.2.51
ARG SUPERCRONIC_SHA256SUM_amd64=cc232108374e8e2b537045f2d5eaa1229f619db314c3ba6a14d38b35dc0aa123
ARG SUPERCRONIC_SHA256SUM_arm64=4ae22576a78223d8ccdf5f3b3660a5cbb5288416bf0ca96afc4a36d195932b94
ARG TARGETARCH
ARG BW_VERSION=2026.10.0
ARG BW_SHA256SUM_amd64=a300959a347bd71ff571da75687c8388da2ecd747a20f0abddd18643eb9466ba
ARG BW_SHA256SUM_arm64=ea6203a565c48d3107bb8511221bb1e436e06c9bc07d05ba679d8921648e83c9
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
    && python -m pip check

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} DRY_RUN=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml ghostfolio_core.py entrypoint.sh ./
COPY ghostfolio_degiro_sync/ ./ghostfolio_degiro_sync/
RUN python -m pip install --no-cache-dir --no-deps . \
    && python -m pip check \
    && python -m pip uninstall -y pip \
    && rm -rf build ghostfolio_degiro_sync.egg-info
COPY scripts/recover_degiro.py ./scripts/recover_degiro.py
COPY degiro_identity_maintenance.py ./degiro_identity_maintenance.py
COPY scripts/migrate_degiro_identity.py ./scripts/migrate_degiro_identity.py
COPY scripts/check_scheduler.py ./scripts/check_scheduler.py
COPY third_party/bitwarden/ /usr/local/share/bitwarden/
RUN chmod 755 /app/entrypoint.sh \
    && groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid appuser --no-create-home --system appuser
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD ["python", "/app/scripts/check_scheduler.py"]
ENTRYPOINT ["/app/entrypoint.sh"]
