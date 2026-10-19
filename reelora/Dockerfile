FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app app.py .
COPY --chown=app:app static ./static
COPY --chown=app:app pages ./pages
USER app
EXPOSE 10000
CMD gunicorn -b 0.0.0.0:${PORT:-10000} -w 2 --threads 4 -t 180 --limit-request-line 2048 --limit-request-fields 50 app:app
