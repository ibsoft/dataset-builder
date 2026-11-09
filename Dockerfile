FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system --gid 10001 dataset \
    && useradd --system --uid 10001 --gid dataset --home /app --shell /usr/sbin/nologin dataset
COPY datasetbuilder ./datasetbuilder
COPY migrations ./migrations
COPY wsgi.py VERSION ./
RUN mkdir -p /app/data/knowledge_base && chown -R dataset:dataset /app/data
USER dataset
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "2", "--worker-class", "gthread", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "wsgi:app"]
