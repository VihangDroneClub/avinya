#!/usr/bin/env bash
# Avinya Backup Script
# Backs up ChromaDB, vault, and sessions to a timestamped archive.
# Usage: ./scripts/backup.sh [backup_dir]
# Run via cron: 0 2 * * * /path/to/avinya/scripts/backup.sh /path/to/backups

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${1:-$ROOT/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_PATH="$BACKUP_DIR/avinya_$TIMESTAMP"

CHROMA_PATH="${AVINYA_CHROMA_PATH:-$ROOT/chroma_db}"
VAULT_PATH="${AVINYA_VAULT_PATH:-$ROOT/vihang_data/vault}"
ARCHIVE_PATH="${AVINYA_ARCHIVE_PATH:-$ROOT/vihang_data/archive}"

mkdir -p "$BACKUP_PATH"

echo "=== Avinya Backup ==="
echo "Timestamp: $TIMESTAMP"
echo "Backup dir: $BACKUP_PATH"

# Backup ChromaDB
if [ -d "$CHROMA_PATH" ]; then
    echo "Backing up ChromaDB..."
    cp -r "$CHROMA_PATH" "$BACKUP_PATH/chroma_db"
    echo "  Done ($(du -sh "$BACKUP_PATH/chroma_db" | cut -f1))"
else
    echo "  ChromaDB not found at $CHROMA_PATH (skipping)"
fi

# Backup vault
if [ -d "$VAULT_PATH" ]; then
    echo "Backing up vault..."
    cp -r "$VAULT_PATH" "$BACKUP_PATH/vault"
    echo "  Done ($(du -sh "$BACKUP_PATH/vault" | cut -f1))"
else
    echo "  Vault not found at $VAULT_PATH (skipping)"
fi

# Backup archive
if [ -d "$ARCHIVE_PATH" ]; then
    echo "Backing up archive..."
    cp -r "$ARCHIVE_PATH" "$BACKUP_PATH/archive"
    echo "  Done ($(du -sh "$BACKUP_PATH/archive" | cut -f1))"
else
    echo "  Archive not found at $ARCHIVE_PATH (skipping)"
fi

# Backup knowledge_base
if [ -d "$ROOT/knowledge_base" ]; then
    echo "Backing up knowledge_base..."
    cp -r "$ROOT/knowledge_base" "$BACKUP_PATH/knowledge_base"
    echo "  Done ($(du -sh "$BACKUP_PATH/knowledge_base" | cut -f1))"
fi

# Create compressed archive
echo "Compressing..."
cd "$BACKUP_DIR"
tar czf "avinya_$TIMESTAMP.tar.gz" "avinya_$TIMESTAMP"
rm -rf "avinya_$TIMESTAMP"

TOTAL_SIZE=$(du -sh "avinya_$TIMESTAMP.tar.gz" | cut -f1)
echo "=== Backup Complete ==="
echo "File: $BACKUP_DIR/avinya_$TIMESTAMP.tar.gz"
echo "Size: $TOTAL_SIZE"

# Cleanup old backups (keep last 7)
BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/avinya_*.tar.gz 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt 7 ]; then
    echo "Cleaning up old backups (keeping last 7)..."
    ls -1t "$BACKUP_DIR"/avinya_*.tar.gz | tail -n +8 | xargs rm -f
    echo "  Removed $((BACKUP_COUNT - 7)) old backup(s)"
fi
