FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/vihang_data/vault /app/vihang_data/inbox /app/vihang_data/archive /app/chroma_db

ENV AVINYA_CHROMA_PATH=/app/chroma_db
ENV AVINYA_VAULT_PATH=/app/vihang_data/vault
ENV AVINYA_INBOX_PATH=/app/vihang_data/inbox
ENV AVINYA_ARCHIVE_PATH=/app/vihang_data/archive
ENV OLLAMA_URL=http://ollama:11434/api/generate

EXPOSE 8080

CMD ["python", "-m", "web.server"]
