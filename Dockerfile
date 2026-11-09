FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY backend ./backend
COPY pipeline ./pipeline
COPY frontend ./frontend

# Utilisateur non-root ; /app/data reçoit la base SQLite (volume)
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
# L'API et l'interface web sont servies par le même processus
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
