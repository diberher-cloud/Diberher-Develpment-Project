FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencias con versiones exactas (requirements.lock); el código se monta o copia después.
COPY requirements.lock ./
RUN pip install -r requirements.lock

COPY . .

# Usuario sin privilegios
RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
