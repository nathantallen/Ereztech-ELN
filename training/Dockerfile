FROM python:3.12-slim

WORKDIR /srv/training

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# /data holds the training records and the editable curriculum (YAML). Persist it
# (see docker-compose.yml) — point it at the NAS or a SharePoint-synced folder.
ENV TRAINING_DATA_DIR=/data
VOLUME /data
EXPOSE 8092

# Single worker with threads: the file store uses in-process locking.
CMD ["gunicorn", "-b", "0.0.0.0:8092", "--workers", "1", "--threads", "8", \
     "--timeout", "60", "app:create_app()"]
