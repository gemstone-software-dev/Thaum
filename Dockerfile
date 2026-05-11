# syntax=docker/dockerfile:1
#
# Build args (combine as needed):
#   THAUM_ENABLE_AZURE=0|1     — gemstone_utils[azure] in the venv (default 0).
#   THAUM_BUNDLED_POSTGRES=0|1 — install PostgreSQL + supervisord in the image (default 1).
#
# Four variants (examples; PYTHON_VERSION optional):
#   docker build -t localhost/thaum:local .
#   docker build --build-arg THAUM_ENABLE_AZURE=1 -t localhost/thaum-azure:local .
#   docker build --build-arg THAUM_BUNDLED_POSTGRES=0 -t localhost/thaum-external-db:local .
#   docker build --build-arg THAUM_ENABLE_AZURE=1 --build-arg THAUM_BUNDLED_POSTGRES=0 \
#     -t localhost/thaum-azure-external-db:local .
#
# Runtime:
#   Bundled image (THAUM_BUNDLED_POSTGRES=1): unset THAUM_EXTERNAL_DB for Unix-socket Postgres + supervisord;
#     or THAUM_EXTERNAL_DB=true + [server.database].db_url for gunicorn only.
#   External-db image (THAUM_BUNDLED_POSTGRES=0): gunicorn only; set [server.database].db_url (THAUM_EXTERNAL_DB not required).
#
# Buildah: buildah bud -t localhost/thaum:local -f Dockerfile .

ARG PYTHON_VERSION=3.13

# --- build stage: venv, PyPI deps + requirements, then strip pip ---
FROM python:${PYTHON_VERSION}-slim AS builder

ARG GEMSTONE_UTILS_REF=0.4.0
ARG THAUM_ENABLE_AZURE=0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
        libssl-dev \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Install gemstone_utils from PyPI first (with or without [azure]); omit its line from requirements.txt for the rest.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && if [ "${THAUM_ENABLE_AZURE}" = "1" ]; then \
         GEMSTONE_SPEC="gemstone_utils[azure]==${GEMSTONE_UTILS_REF}"; \
       else \
         GEMSTONE_SPEC="gemstone_utils==${GEMSTONE_UTILS_REF}"; \
       fi \
    && pip install --no-cache-dir "${GEMSTONE_SPEC}" \
    && grep -v '^gemstone_utils' requirements.txt > /tmp/requirements.nopypi-eu.txt \
    && pip install --no-cache-dir -r /tmp/requirements.nopypi-eu.txt \
    && pip uninstall -y pip setuptools wheel \
    && rm -f /venv/bin/pip /venv/bin/pip3 /venv/bin/pip3.* 2>/dev/null || true

# --- runtime: copy venv + app only ---
FROM python:${PYTHON_VERSION}-slim AS runtime

ARG THAUM_BUNDLED_POSTGRES=1
ARG THAUM_IMAGE_VERSION=unknown
ARG THAUM_IMAGE_CHANNEL=local
LABEL org.opencontainers.image.version="${THAUM_IMAGE_VERSION}" \
      thaum.image.channel="${THAUM_IMAGE_CHANNEL}" \
      thaum.image.bundled_postgres="${THAUM_BUNDLED_POSTGRES}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && if [ "${THAUM_BUNDLED_POSTGRES}" = "1" ]; then \
         apt-get install -y --no-install-recommends \
             postgresql \
             postgresql-client \
             supervisor \
         && PG_BINDIR="$(ls -d /usr/lib/postgresql/*/bin | head -n1)" \
         && for f in initdb pg_ctl postgres pg_isready; do \
                ln -sf "${PG_BINDIR}/${f}" "/usr/local/bin/${f}"; \
            done; \
       fi \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin thaum \
    && if [ "${THAUM_BUNDLED_POSTGRES}" = "1" ]; then usermod -aG postgres thaum; fi

WORKDIR /app
# Do not set THAUM_CONFIG_FILE in the image. Let runtime configuration decide config location.
# Prefer .toml over .conf for the same TOML content for better editor syntax highlighting.
ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    THAUM_IMAGE_BUNDLED_POSTGRES=${THAUM_BUNDLED_POSTGRES}

COPY --from=builder /venv /venv
COPY --chown=1000:1000 . .

COPY docker/supervisord.conf /tmp/thaum-supervisord.conf
RUN if [ "${THAUM_BUNDLED_POSTGRES}" = "1" ]; then \
        install -d /etc/supervisor \
        && mv /tmp/thaum-supervisord.conf /etc/supervisor/supervisord.conf; \
    else \
        rm -f /tmp/thaum-supervisord.conf; \
    fi

RUN chmod +x \
        /app/docker/entrypoint.sh \
        /app/docker/wait_for_pg.sh \
        /app/docker/run_thaum.sh \
        /app/docker/pg_bootstrap.py

USER root
VOLUME ["/etc/thaum", "/var/lib/thaum"]
EXPOSE 5165

# Default 0.0.0.0: reverse proxy reaches this container via its own IP.
# Do not publish this port to the public host; expose only the proxy.
ENV GUNICORN_BIND=0.0.0.0:5165
ENV GUNICORN_WORKERS=1
ENV THAUM_JSON_LOG=true

ENTRYPOINT ["/app/docker/entrypoint.sh"]
