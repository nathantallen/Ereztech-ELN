FROM python:3.12-slim

# ffmpeg assembles camera recordings from snapshot frames
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg curl unzip \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libcairo2 \
      libgdk-pixbuf-2.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# rclone moves closed-out entries to OneDrive (app/archive.py). Pinned and
# checksum-verified against the release manifest rather than piped from an
# installer script.
ARG RCLONE_VERSION=v1.75.0
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    zip="rclone-${RCLONE_VERSION}-linux-${arch}.zip"; \
    curl -fsSLO "https://downloads.rclone.org/${RCLONE_VERSION}/${zip}"; \
    curl -fsSLO "https://downloads.rclone.org/${RCLONE_VERSION}/SHA256SUMS"; \
    sha256sum --ignore-missing -c SHA256SUMS 2>&1 | grep "${zip}: OK"; \
    unzip -q "${zip}"; \
    install -m 0755 "rclone-${RCLONE_VERSION}-linux-${arch}/rclone" /usr/local/bin/rclone; \
    rm -rf "${zip}" SHA256SUMS "rclone-${RCLONE_VERSION}-linux-${arch}"; \
    rclone version | head -1

WORKDIR /srv/eln

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# /data holds the notebook; /config holds the tiny storage-location pointer that
# survives the data dir being re-pointed. BOTH must be persisted (see
# docker-compose.yml) — declaring them here documents the dependency so a run
# without the mounts doesn't silently lose the pointer on recreate.
ENV ELN_DATA_DIR=/data
ENV ELN_CONFIG_DIR=/config
# Archiving stays off unless ELN_ARCHIVE_REMOTE is set (see docker-compose.yml).
ENV RCLONE_CONFIG=/rclone/rclone.conf
VOLUME /data
VOLUME /config
EXPOSE 8091

# Single worker with threads: the file store uses in-process locking.
# Long timeout allows large video uploads.
CMD ["gunicorn", "-b", "0.0.0.0:8091", "--workers", "1", "--threads", "8", \
     "--timeout", "600", "app:create_app()"]
