FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system .

COPY . .

ENV DB_PATH=/data/stocks.db

CMD ["python", "run.py", "--mode", "update"]
