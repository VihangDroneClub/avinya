# Avinya Deployment Guide

## Quick Deploy (Docker)

```bash
# Clone the repo
git clone https://github.com/VihangDroneClub/avinya.git
cd avinya

# Set your PIN
export AVINYA_WEB_PIN=your-secret-pin

# Start everything
docker compose up -d

# Ingest knowledge base
docker compose exec avinya python scripts/ingest_knowledge_base.py
```

Access at `http://<server-ip>:8080`

## Manual Deploy (Linux Server / Raspberry Pi)

### 1. Install dependencies

```bash
# System packages
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git curl

# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull models
ollama pull gemma2:2b-instruct-q4_K_M
ollama pull hermes3:8b-llama3.1-q4_K_M
ollama pull nomic-embed-text
```

### 2. Set up Avinya

```bash
# Clone
git clone https://github.com/VihangDroneClub/avinya.git /opt/avinya
cd /opt/avinya

# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create data directories
mkdir -p vihang_data/vault vihang_data/inbox vihang_data/archive chroma_db backups

# Ingest knowledge base
python scripts/ingest_knowledge_base.py
```

### 3. Set up systemd services

```bash
# Copy service files
sudo cp scripts/avinya.service /etc/systemd/system/
sudo cp scripts/ollama.service /etc/systemd/system/

# Create user (if needed)
sudo useradd --system --home /opt/avinya avinya
sudo chown -R avinya:avinya /opt/avinya

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable ollama avinya
sudo systemctl start ollama
sudo systemctl start avinya

# Check status
sudo systemctl status avinya
sudo journalctl -u avinya -f
```

### 4. Set up automated backups

```bash
# Add to crontab (runs daily at 2 AM)
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/avinya/scripts/backup.sh /opt/avinya/backups") | crontab -

# Or run manually
./scripts/backup.sh /opt/avinya/backups
```

### 5. Firewall (optional)

```bash
# Allow access from local network only
sudo ufw allow from 192.168.0.0/16 to any port 8080
sudo ufw allow from 10.0.0.0/8 to any port 8080
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AVINYA_WEB_PIN` | `vihang2026` | Web interface access PIN |
| `OLLAMA_URL` | `http://127.0.0.1:11434/api/generate` | Ollama API URL |
| `AVINYA_CHROMA_PATH` | `./chroma_db` | ChromaDB data directory |
| `AVINYA_VAULT_PATH` | `./vihang_data/vault` | Document vault |
| `AVINYA_INBOX_PATH` | `./vihang_data/inbox` | Inbox for new documents |
| `AVINYA_ARCHIVE_PATH` | `./vihang_data/archive` | Archived originals |

## Troubleshooting

### Avinya won't start
```bash
sudo journalctl -u avinya -n 50 --no-pager
```

### Ollama not responding
```bash
curl http://127.0.0.1:11434/api/tags
sudo journalctl -u ollama -n 50 --no-pager
```

### Reset everything
```bash
sudo systemctl stop avinya ollama
rm -rf /opt/avinya/chroma_db /opt/avinya/vihang_data
# Then re-run setup from step 2
```
