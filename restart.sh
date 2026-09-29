#!/bin/bash

# Paths
PROJECT_DIR="/home/agent/projects/tg-minecraft"
BOT_DIR="/home/podman-svc/pod/bot-minecraft"
SERVICE_NAME="bot-minecraft.service"

echo "🚀 Updating bot files..."
tar -czf /tmp/bot_update.tar.gz -C $PROJECT_DIR bot .env
scp /tmp/bot_update.tar.gz podman-svc:~/bot_update.tar.gz
ssh podman-svc "mkdir -p $BOT_DIR && tar -xzf ~/bot_update.tar.gz -C $BOT_DIR && rm ~/bot_update.tar.gz"

echo "🛠 Preparing virtual environment..."
ssh podman-svc "python3 -m venv $BOT_DIR/venv && $BOT_DIR/venv/bin/pip install --upgrade pip && $BOT_DIR/venv/bin/pip install -r $BOT_DIR/bot/requirements.txt"

echo "🔄 Installing systemd unit..."
ssh podman-svc "mkdir -p ~/.config/systemd/user/ && scp /tmp/bot-minecraft.service podman-svc:~/.config/systemd/user/$SERVICE_NAME" 2>/dev/null || \
ssh podman-svc "mkdir -p ~/.config/systemd/user/ && cat <<EOF > ~/.config/systemd/user/$SERVICE_NAME
[Unit]
Description=Minecraft Management Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$BOT_DIR
ExecStart=$BOT_DIR/venv/bin/python $BOT_DIR/bot/main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF"

echo "🚀 Restarting bot service..."
ssh podman-svc "systemctl --user daemon-reload && systemctl --user enable $SERVICE_NAME && systemctl --user restart $SERVICE_NAME"

if [ $? -eq 0 ]; then
    echo "✅ Bot deployed and restarted successfully as a systemd unit!"
else
    echo "❌ Failed to restart bot."
    exit 1
fi
