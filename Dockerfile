FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

# Cloud Run injects PORT; server.py reads it (defaults to 8080 locally).
CMD ["python", "server.py"]
