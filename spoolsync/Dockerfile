# https://developers.home-assistant.io/docs/apps/configuration#app-dockerfile
ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.13-alpine3.24
FROM ${BUILD_FROM}

# Python-Abhängigkeiten – vorgebaute Wheels bevorzugen, Compiler nur temporär als Fallback.
COPY requirements.txt /tmp/requirements.txt
RUN apk add --no-cache --virtual .build-deps gcc musl-dev \
    && pip3 install --no-cache-dir \
        --extra-index-url "https://wheels.home-assistant.io/musllinux-index/" \
        -r /tmp/requirements.txt \
    && apk del .build-deps \
    && rm /tmp/requirements.txt

COPY rootfs /
RUN chmod a+x /etc/services.d/spoolsync/run /etc/services.d/spoolsync/finish

WORKDIR /opt

LABEL \
    org.opencontainers.image.title="Home Assistant App: SpoolSync" \
    org.opencontainers.image.description="Two-way spool sync between Spoolman and the Bambu Lab cloud" \
    org.opencontainers.image.source="https://github.com/Telo87/ha-spoolsync" \
    org.opencontainers.image.licenses="MIT"
