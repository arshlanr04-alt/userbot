import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Telegram API credentials
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

# Bot Token (used if running as a bot client)
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Parse Admin IDs
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = []
if ADMIN_IDS_RAW:
    for admin_id in ADMIN_IDS_RAW.split(","):
        admin_id = admin_id.strip()
        if admin_id.isdigit():
            ADMIN_IDS.append(int(admin_id))
        elif admin_id.startswith("-") and admin_id[1:].isdigit():
            # Support negative IDs just in case
            ADMIN_IDS.append(int(admin_id))

# Verify configurations
if API_ID and API_ID.isdigit():
    API_ID = int(API_ID)
else:
    API_ID = None

# Print warnings for developer visibility during startup
if not API_ID or not API_HASH:
    print("WARNING: API_ID or API_HASH is missing from environment. Pyrogram client may not start.")
if not BOT_TOKEN:
    print("WARNING: BOT_TOKEN is missing. The bot will run as a userbot if a session is active, or fail to start.")
if not ADMIN_IDS:
    print("WARNING: ADMIN_IDS list is empty. No one will have access to the admin panel.")
else:
    print(f"Loaded {len(ADMIN_IDS)} admin ID(s): {ADMIN_IDS}")
