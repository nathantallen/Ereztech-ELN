FROM python:3.12-slim

# ffmpeg assembles camera recordings from snapshot frames
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

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
VOLUME /data
VOLUME /config
EXPOSE 8091

# Single worker with threads: the file store uses in-process locking.
# Long timeout allows large video uploads.
CMD ["gunicorn", "-b", "0.0.0.0:8091", "--workers", "1", "--threads", "8", \
     "--timeout", "600", "app:create_app()"]
