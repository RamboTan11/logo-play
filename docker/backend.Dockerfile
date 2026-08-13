FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY backend ./backend
COPY pycore ./pycore

RUN pip install --no-cache-dir .

ENV PYTHONPATH=/app/backend:/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8099

CMD ["uvicorn", "src.docker:create_app", "--factory", "--host", "0.0.0.0", "--port", "8099"]
