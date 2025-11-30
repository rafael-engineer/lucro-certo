FROM python:3.13.9-slim

LABEL maintainer="Rafael da Silva Santos <contact@rafael.engineer>"
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    libpq-dev \
    git \
    curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN useradd --create-home --shell /bin/bash appuser \
  && chown -R appuser:appuser /app

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
  && pip install --no-cache-dir -r /app/requirements.txt

COPY --chown=appuser:appuser . /app

USER appuser

EXPOSE 8501

CMD ["sh", "-c", "streamlit run src/app.py --server.address 0.0.0.0 --server.port ${PORT:-8501}"]
