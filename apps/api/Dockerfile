FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY apps/api /app

RUN pip install --no-cache-dir .

CMD ["uvicorn", "self_healing_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
