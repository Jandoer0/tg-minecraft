import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_API_BOT")
ALLOWED_USERS = [int(uid) for uid in os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",") if uid]

# Minecraft Config
CONTAINER_NAME = "minecraft-1"
SERVICE_NAME = "minecraft-forge_1.service"
DATA_PATH = "/mnt/library/containers/minecraft/data"
SERVER_PROPS = os.path.join(DATA_PATH, "server.properties")
WORLD_PREFIX = "world_"
