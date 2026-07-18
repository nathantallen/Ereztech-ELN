FROM python:3.12-slim
WORKDIR /srv/mockha
RUN pip install --no-cache-dir flask pillow
COPY app.py .
EXPOSE 8123
CMD ["python", "app.py"]
