#!/usr/bin/env bash
set -euo pipefail

BASE_URL="https://raw.githubusercontent.com/chapmanjacobd/syncweb-py/refs/heads/main/examples"

SERVICE_URL="$BASE_URL/syncweb-automatic.service"

SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

SERVICE_DST="$SYSTEMD_USER_DIR/syncweb-automatic.service"

mkdir -p "$SYSTEMD_USER_DIR"

echo "Downloading systemd user service..."
curl -fsSL "$SERVICE_URL" -o "$SERVICE_DST"
chmod 0644 "$SERVICE_DST"

systemctl --user daemon-reload
echo "Enabling syncweb-automatic user service..."
systemctl --user enable --now syncweb-automatic.service

echo
echo "Installation complete."
echo "systemctl --user status syncweb-automatic.service"
systemctl --user status syncweb-automatic.service
