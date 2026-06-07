import sys
import asyncio
import logging
from pyrogram import Client, idle
import config
import database as db

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = None

# Import handlers here to execute their decorators
import start_handler
import admin_panel

async def start_services():
    """Initializes the database and starts the bot."""
    global app
    
    # Validate credentials
    if not config.API_ID or not config.API_HASH:
        logger.critical("FATAL: API_ID and API_HASH must be configured in .env!")
        return

    # Initialize Client
    if config.BOT_TOKEN:
        logger.info("Configuring Pyrogram client in Bot Mode...")
        app = Client(
            "my_bot",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=config.BOT_TOKEN
        )
    else:
        logger.info("Configuring Pyrogram client in Userbot Mode...")
        app = Client(
            "my_userbot",
            api_id=config.API_ID,
            api_hash=config.API_HASH
        )

    logger.info("Initializing SQLite database...")
    try:
        await db.init_db()
        logger.info("✅ Database initialized successfully.")
    except Exception as e:
        logger.critical(f"FATAL: Failed to initialize database: {e}", exc_info=True)
        return

    logger.info("Starting Pyrogram Client...")
    try:
        await app.start()
        # Fetch bot user info to print username
        me = await app.get_me()
        logger.info(f"✅ Bot started successfully! Running as: @{me.username or me.first_name} (ID: {me.id})")
    except Exception as e:
        logger.critical(f"FATAL: Failed to start Pyrogram client: {e}", exc_info=True)
        return

    logger.info("Bot is active and listening for messages. Press Ctrl+C to stop.")
    await idle()

    logger.info("Stopping Pyrogram Client...")
    await app.stop()
    logger.info("✅ Stopped successfully.")

if __name__ == "__main__":
    try:
        asyncio.run(start_services())
    except KeyboardInterrupt:
        logger.info("Application interrupted by user. Exiting...")
