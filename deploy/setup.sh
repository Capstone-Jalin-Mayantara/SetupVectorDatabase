#!/bin/bash
# Setup lengkap ASIQ di EC2 Ubuntu 22.04
# Jalankan sebagai user ubuntu: bash setup.sh
set -e

REPO_DIR="/home/ubuntu/SetupVectorDatabase"
VENV_DIR="/home/ubuntu/venv"
SERVICE_NAME="asiq"
DOMAIN="${1:-}"   # Opsional: bash setup.sh api.asiq.jalin.id

echo "=== ASIQ Production Setup ==="

# 1. Update & install dependencies sistem
echo "[1/8] Install dependencies sistem..."
sudo apt-get update -qq
sudo apt-get install -y python3.10 python3.10-venv python3-pip nginx certbot python3-certbot-nginx

# 2. Setup virtual environment
echo "[2/8] Setup Python venv..."
python3.10 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r "$REPO_DIR/requirements.txt" -q
echo "Venv siap di $VENV_DIR"

# 3. Pastikan .env ada
echo "[3/8] Cek .env..."
if [ ! -f "$REPO_DIR/.env" ]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo "PENTING: Edit $REPO_DIR/.env dan isi API key yang benar sebelum lanjut!"
    echo "  nano $REPO_DIR/.env"
fi

# 4. Inisialisasi ChromaDB
echo "[4/8] Inisialisasi ChromaDB..."
cd "$REPO_DIR"
source "$VENV_DIR/bin/activate"
python init_chroma.py || echo "ChromaDB sudah terinisialisasi, skip."

# 5. Ingest dokumen pedoman (jika folder knowledge/ ada)
if [ -d "$REPO_DIR/knowledge" ] && [ "$(ls -A $REPO_DIR/knowledge)" ]; then
    echo "[5/8] Ingest dokumen pedoman ke ChromaDB..."
    python ingest_pedoman.py
else
    echo "[5/8] Folder knowledge/ kosong, skip ingest."
fi

# 6. Install systemd service
echo "[6/8] Install systemd service..."
sudo cp "$REPO_DIR/deploy/asiq.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
echo "Service ASIQ aktif dan akan auto-start saat reboot."

# 7. Setup nginx (jika domain diberikan)
if [ -n "$DOMAIN" ]; then
    echo "[7/8] Setup nginx untuk domain: $DOMAIN..."
    sudo sed "s/DOMAIN_KAMU/$DOMAIN/g" "$REPO_DIR/deploy/nginx.conf" \
        > /tmp/asiq_nginx.conf
    sudo mv /tmp/asiq_nginx.conf /etc/nginx/sites-available/asiq
    sudo ln -sf /etc/nginx/sites-available/asiq /etc/nginx/sites-enabled/asiq
    sudo rm -f /etc/nginx/sites-enabled/default
    sudo nginx -t && sudo systemctl reload nginx

    echo "[8/8] Generate SSL certificate dengan Let's Encrypt..."
    sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m admin@jalin.id || \
        echo "Certbot gagal — pastikan domain sudah pointing ke IP EC2 ini."
else
    echo "[7/8] Domain tidak diberikan, skip nginx/SSL setup."
    echo "      Jalankan lagi dengan: bash setup.sh api.asiq.jalin.id"
    echo "[8/8] Skip SSL."
fi

# Setup cron backup ChromaDB harian jam 3 pagi
echo "Setup cron backup ChromaDB..."
(crontab -l 2>/dev/null; echo "0 3 * * * curl -s -X POST http://localhost:8000/api/admin/backup-chroma -H 'X-API-Key: \$API_KEY' >> /var/log/asiq_backup.log 2>&1") | crontab -

echo ""
echo "=== Setup selesai! ==="
echo "Status service  : sudo systemctl status asiq"
echo "Log real-time   : sudo journalctl -u asiq -f"
echo "Test API        : curl http://localhost:8000/health"
if [ -n "$DOMAIN" ]; then
    echo "API production  : https://$DOMAIN/docs"
fi
