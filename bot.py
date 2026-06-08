import os
import json
import logging
import asyncio
import sqlite3
import psycopg2
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Dynamic Pyrogram Import to prevent crash if not installed
try:
    import pyrogram
    from pyrogram import Client
    PYROGRAM_AVAILABLE = True
except ImportError:
    PYROGRAM_AVAILABLE = False

# Setup logging with a premium-looking format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [🤖 BOT] - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants and Configuration Paths
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))

# Temporary store for ongoing userbot login attempts
# format: { user_id: { "client": Client, "phone": str, "phone_code_hash": str, "simulation": bool } }
temp_userbot_logins = {}

# Temporary store for /forward confirmations
temp_forward_confirms = {}

# Active forwarding tasks
active_forwarding_tasks = {}

import threading

# Create a global background event loop to run all Pyrogram tasks
background_loop = asyncio.new_event_loop()

def start_background_loop(loop_to_run):
    asyncio.set_event_loop(loop_to_run)
    loop_to_run.run_forever()

# Start loop in a background daemon thread
loop_thread = threading.Thread(target=start_background_loop, args=(background_loop,), daemon=True)
loop_thread.start()
logger.info("Initialized background event loop thread for Pyrogram integrations.")

def run_async(coro):
    """Schedules a coroutine to run on the background loop and blocks until it returns a result."""
    future = asyncio.run_coroutine_threadsafe(coro, background_loop)
    return future.result()

# --- DATABASE MANAGER (PostgreSQL with SQLite fallback) ---
class DBManager:
    def __init__(self):
        self.db_url = os.environ.get("DATABASE_URL")
        self.is_postgres = False
        self.init_db()

    def get_connection(self):
        if self.db_url:
            try:
                # Standardize postgres:// to postgresql:// for psycopg2 compatibility
                url = self.db_url
                if url.startswith("postgres://"):
                    url = url.replace("postgres://", "postgresql://", 1)
                conn = psycopg2.connect(url)
                self.is_postgres = True
                return conn
            except Exception as e:
                logger.error(f"Failed to connect to PostgreSQL via DATABASE_URL: {e}. Falling back to SQLite.")
        
        # SQLite Fallback
        self.is_postgres = False
        sqlite_file = os.path.join(CONFIG_DIR, "bot.db")
        return sqlite3.connect(sqlite_file)

    def execute_query(self, query, params=(), commit=False, fetch=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # PostgreSQL uses %s placeholders, SQLite uses ?
            if not self.is_postgres:
                query = query.replace("%s", "?")
            cursor.execute(query, params)
            if commit:
                conn.commit()
            if fetch == "one":
                return cursor.fetchone()
            elif fetch == "all":
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Database query error: {e}. Query: {query}")
            if commit:
                try:
                    conn.rollback()
                except:
                    pass
        finally:
            cursor.close()
            conn.close()

    def init_db(self):
        if self.db_url:
            # PostgreSQL schema
            try:
                self.execute_query(
                    "CREATE TABLE IF NOT EXISTS settings ("
                    "key VARCHAR(50) PRIMARY KEY, "
                    "value TEXT"
                    ")", commit=True
                )
                self.execute_query(
                    "CREATE TABLE IF NOT EXISTS linked_bots ("
                    "id SERIAL PRIMARY KEY, "
                    "user_id BIGINT, "
                    "bot_token TEXT, "
                    "bot_name TEXT, "
                    "bot_username TEXT, "
                    "bot_telegram_id BIGINT, "
                    "active BOOLEAN DEFAULT TRUE, "
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                    ")", commit=True
                )
                self.execute_query(
                    "CREATE TABLE IF NOT EXISTS linked_userbots ("
                    "id SERIAL PRIMARY KEY, "
                    "user_id BIGINT, "
                    "phone TEXT, "
                    "session_string TEXT, "
                    "first_name TEXT, "
                    "username TEXT, "
                    "active BOOLEAN DEFAULT TRUE, "
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                    ")", commit=True
                )
                self.execute_query(
                    "CREATE TABLE IF NOT EXISTS target_chats ("
                    "id SERIAL PRIMARY KEY, "
                    "user_id BIGINT, "
                    "chat_id BIGINT, "
                    "chat_title TEXT, "
                    "chat_username TEXT, "
                    "active BOOLEAN DEFAULT TRUE, "
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                    ")", commit=True
                )
                self.execute_query(
                    "CREATE TABLE IF NOT EXISTS user_settings ("
                    "user_id BIGINT PRIMARY KEY, "
                    "custom_caption TEXT, "
                    "filters TEXT, "
                    "remove_words TEXT"
                    ")", commit=True
                )
            except Exception as e:
                logger.critical(f"Failed to initialize PostgreSQL schema: {e}")
        else:
            # SQLite schema
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS settings ("
                "key TEXT PRIMARY KEY, "
                "value TEXT"
                ")"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS linked_bots ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id INTEGER, "
                "bot_token TEXT, "
                "bot_name TEXT, "
                "bot_username TEXT, "
                "bot_telegram_id INTEGER, "
                "active INTEGER DEFAULT 1, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS linked_userbots ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id INTEGER, "
                "phone TEXT, "
                "session_string TEXT, "
                "first_name TEXT, "
                "username TEXT, "
                "active INTEGER DEFAULT 1, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS target_chats ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id INTEGER, "
                "chat_id INTEGER, "
                "chat_title TEXT, "
                "chat_username TEXT, "
                "active INTEGER DEFAULT 1, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
            conn.commit()
            cursor.close()
            conn.close()
            
        # Run safe migrations to add new columns to linked_bots if they are missing
        try:
            self.execute_query("ALTER TABLE linked_bots ADD COLUMN bot_name TEXT", commit=True)
        except Exception:
            pass
        try:
            self.execute_query("ALTER TABLE linked_bots ADD COLUMN bot_username TEXT", commit=True)
        except Exception:
            pass
        try:
            self.execute_query("ALTER TABLE linked_bots ADD COLUMN bot_telegram_id BIGINT", commit=True)
        except Exception:
            pass
            
        # Run safe migrations to add new columns to linked_userbots if they are missing
        try:
            self.execute_query("ALTER TABLE linked_userbots ADD COLUMN first_name TEXT", commit=True)
        except Exception:
            pass
        try:
            self.execute_query("ALTER TABLE linked_userbots ADD COLUMN username TEXT", commit=True)
        except Exception:
            pass
            
        # Run safe migrations to create target_chats and user_settings if sqlite database was already created
        if not self.db_url:
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS target_chats ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "user_id INTEGER, "
                    "chat_id INTEGER, "
                    "chat_title TEXT, "
                    "chat_username TEXT, "
                    "active INTEGER DEFAULT 1, "
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS user_settings ("
                    "user_id INTEGER PRIMARY KEY, "
                    "custom_caption TEXT, "
                    "filters TEXT, "
                    "remove_words TEXT"
                    ")"
                )
                conn.commit()
                cursor.close()
                conn.close()
            except Exception:
                pass
            
        logger.info("Database initialized successfully.")

# Initialize DB Manager
db = DBManager()

def get_user_settings(user_id):
    """Retrieves settings for a specific user, creating default settings if missing."""
    row = db.execute_query(
        "SELECT custom_caption, filters, remove_words FROM user_settings WHERE user_id = %s",
        (user_id,), fetch="one"
    )
    if not row:
        default_filters = {
            "forward_tag": False,
            "texts": True,
            "documents": True,
            "videos": True,
            "photos": True,
            "audios": True,
            "voices": True,
            "animations": True,
            "stickers": True,
            "skip_duplicate": True,
            "poll": True,
            "secure_message": False
        }
        filters_json = json.dumps(default_filters)
        empty_words_json = json.dumps([])
        try:
            db.execute_query(
                "INSERT INTO user_settings (user_id, custom_caption, filters, remove_words) VALUES (%s, %s, %s, %s)",
                (user_id, None, filters_json, empty_words_json), commit=True
            )
        except Exception as e:
            logger.error(f"Error inserting default user settings: {e}")
        return {
            "custom_caption": None,
            "filters": default_filters,
            "remove_words": []
        }
    
    custom_caption, filters_str, remove_words_str = row
    try:
        filters = json.loads(filters_str) if filters_str else {}
    except:
        filters = {}
    try:
        remove_words = json.loads(remove_words_str) if remove_words_str else []
    except:
        remove_words = []
        
    return {
        "custom_caption": custom_caption,
        "filters": filters,
        "remove_words": remove_words
    }

def save_user_settings(user_id, settings):
    """Saves user settings back to the database."""
    filters_str = json.dumps(settings.get("filters", {}))
    remove_words_str = json.dumps(settings.get("remove_words", []))
    custom_caption = settings.get("custom_caption")
    
    row = db.execute_query("SELECT user_id FROM user_settings WHERE user_id = %s", (user_id,), fetch="one")
    if row:
        db.execute_query(
            "UPDATE user_settings SET custom_caption = %s, filters = %s, remove_words = %s WHERE user_id = %s",
            (custom_caption, filters_str, remove_words_str, user_id), commit=True
        )
    else:
        db.execute_query(
            "INSERT INTO user_settings (user_id, custom_caption, filters, remove_words) VALUES (%s, %s, %s, %s)",
            (user_id, custom_caption, filters_str, remove_words_str), commit=True
        )

def get_progress_bar(pct):
    """Generates a 20-character diamond progress bar string representing progress percentage."""
    filled = int(round((pct / 100.0) * 20))
    hollow = 20 - filled
    return "◆" * filled + "◇" * hollow

async def run_forwarding_task(user_id, source_id, target_chat_id, status_message_id, chat_id):
    """Background task that runs the forwarding logic from oldest to newest messages."""
    stats = {
        "fetched": 0,
        "forwarded": 0,
        "duplicates": 0,
        "deleted": 0,
        "skipped": 0,
        "filtered": 0,
        "status": "Forwarding",
        "progress": 0
    }
    
    active_forwarding_tasks[user_id] = {
        "cancelled": False,
        "stats": stats,
        "message_id": status_message_id,
        "chat_id": chat_id
    }
    
    # Retrieve linked bot and userbot details
    bot_row = db.execute_query("SELECT bot_token FROM linked_bots WHERE user_id = %s ORDER BY id DESC", (user_id,), fetch="one")
    ub_row = db.execute_query("SELECT session_string FROM linked_userbots WHERE user_id = %s ORDER BY id DESC", (user_id,), fetch="one")
    
    # User settings (caption, filters, remove words)
    user_settings = get_user_settings(user_id)
    caption_template = user_settings.get("custom_caption")
    filters = user_settings.get("filters", {})
    remove_words = user_settings.get("remove_words", [])
    
    # Determine if we run in simulation mode
    is_simulation = True
    has_real_userbot = ub_row and ub_row[0] and not ub_row[0].startswith("SIMULATED")
    has_real_bot = bot_row and bot_row[0] and bot_row[0] != "YOUR_BOT_TOKEN_HERE" and not bot_row[0].startswith("SIMULATED")
    if has_real_userbot or has_real_bot:
        is_simulation = False
        
    def update_status_message(is_done=False):
        progress_bar = get_progress_bar(stats["progress"])
        status_text = "Completed" if is_done else stats["status"]
        if active_forwarding_tasks.get(user_id, {}).get("cancelled"):
            status_text = "Cancelled"
        hourglass_text = "✅ Done" if is_done else "⏳ Processing"
        
        text = (
            "✨ <b>FORWARD STATUS</b>\n\n"
            "<blockquote>"
            f"📥 <b>FETCHED:</b> {stats['fetched']}\n"
            f"📤 <b>FORWARDED:</b> {stats['forwarded']}\n"
            f"🔄 <b>DUPLICATES:</b> {stats['duplicates']}\n"
            f"🗑️ <b>DELETED:</b> {stats['deleted']}\n"
            f"⏭️ <b>SKIPPED:</b> {stats['skipped']}\n"
            f"🎯 <b>FILTERED:</b> {stats['filtered']}\n"
            f"⚡ <b>STATUS:</b> {status_text}\n"
            f"📊 <b>PROGRESS:</b> {stats['progress']}%\n\n"
            f"✨ {hourglass_text}"
            "</blockquote>"
        )
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(progress_bar, callback_data="progress_bar_click"))
        if not is_done and status_text == "Forwarding":
            markup.add(InlineKeyboardButton("❌ Cancel", callback_data="cancel_forward_task"))
            
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=text,
                reply_markup=markup,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error editing status message: {e}")

    if is_simulation:
        # Run Simulation Mode
        total_messages = 45
        import random
        for i in range(1, total_messages + 1):
            if active_forwarding_tasks.get(user_id, {}).get("cancelled"):
                stats["status"] = "Cancelled"
                update_status_message(is_done=True)
                return
                
            stats["fetched"] += 1
            rand = random.random()
            if rand < 0.1:
                stats["duplicates"] += 1
            elif rand < 0.15:
                stats["skipped"] += 1
            elif rand < 0.2:
                stats["filtered"] += 1
            else:
                stats["forwarded"] += 1
                
            stats["progress"] = int((i / total_messages) * 100)
            update_status_message(is_done=(i == total_messages))
            await asyncio.sleep(1.0)
            
        active_forwarding_tasks.pop(user_id, None)
    else:
        # Real Mode using Pyrogram
        session = ub_row[0] if (ub_row and ub_row[0]) else None
        bot_token = bot_row[0] if (bot_row and bot_row[0]) else None
        
        API_ID = os.environ.get("API_ID") or config.get("api_id")
        API_HASH = os.environ.get("API_HASH") or config.get("api_hash")
        
        if session and not session.startswith("SIMULATED"):
            client = Client(
                name=f"forwarder_{user_id}",
                api_id=int(API_ID),
                api_hash=API_HASH,
                session_string=session,
                in_memory=True
            )
        elif bot_token and not bot_token.startswith("SIMULATED"):
            client = Client(
                name=f"forwarder_{user_id}",
                api_id=int(API_ID),
                api_hash=API_HASH,
                bot_token=bot_token,
                in_memory=True
            )
        else:
            stats["status"] = "No credentials"
            update_status_message(is_done=True)
            return
        
        try:
            await client.connect()
            
            # Populate peer database cache for numeric IDs
            try:
                async for dialog in client.get_dialogs(limit=100):
                    pass
            except Exception as e:
                logger.warning(f"Failed to fetch dialogs in forwarding task: {e}")
            
            # Resolve source chat entity (can be ID or username)
            try:
                resolved_chat = await client.get_chat(source_id)
                resolved_chat_id = resolved_chat.id
            except Exception as e:
                logger.error(f"Failed to resolve source chat entity: {e}")
                resolved_chat_id = source_id
                
            # Fetch all messages from newest to oldest
            stats["status"] = "Fetching messages..."
            update_status_message()
            
            messages_list = []
            try:
                async for msg in client.get_chat_history(resolved_chat_id):
                    if active_forwarding_tasks.get(user_id, {}).get("cancelled"):
                        break
                    messages_list.append(msg)
                    if len(messages_list) % 50 == 0:
                        stats["status"] = f"Fetching ({len(messages_list)})..."
                        update_status_message()
            except Exception as fe:
                logger.error(f"Error fetching history: {fe}")
                stats["status"] = f"Fetch Error: {str(fe)[:25]}"
                update_status_message(is_done=True)
                await client.disconnect()
                return

            if active_forwarding_tasks.get(user_id, {}).get("cancelled"):
                stats["status"] = "Cancelled"
                update_status_message(is_done=True)
                await client.disconnect()
                return
                
            messages_list.reverse()
            total = len(messages_list)
            
            if total == 0:
                stats["status"] = "Source chat is empty"
                update_status_message(is_done=True)
                await client.disconnect()
                return
                
            stats["status"] = "Forwarding"
            update_status_message()
            
            count = 0
            for msg in messages_list:
                if active_forwarding_tasks.get(user_id, {}).get("cancelled"):
                    stats["status"] = "Cancelled"
                    update_status_message(is_done=True)
                    break
                    
                count += 1
                stats["fetched"] += 1
                stats["progress"] = int((count / total) * 100) if total > 0 else 100
                
                # Apply Type Filters
                is_matched = True
                if msg.text:
                    if not filters.get("texts", True):
                        is_matched = False
                elif msg.document:
                    if not filters.get("documents", True):
                        is_matched = False
                elif msg.video:
                    if not filters.get("videos", True):
                        is_matched = False
                elif msg.photo:
                    if not filters.get("photos", True):
                        is_matched = False
                elif msg.audio:
                    if not filters.get("audios", True):
                        is_matched = False
                elif msg.voice:
                    if not filters.get("voices", True):
                        is_matched = False
                elif msg.animation:
                    if not filters.get("animations", True):
                        is_matched = False
                elif msg.sticker:
                    if not filters.get("stickers", True):
                        is_matched = False
                elif msg.poll:
                    if not filters.get("poll", True):
                        is_matched = False
                else:
                    # Skip unsupported/service messages
                    is_matched = False
                    
                if not is_matched:
                    stats["filtered"] += 1
                    update_status_message(is_done=(count == total))
                    continue
                    
                try:
                    # Process Caption variables
                    new_caption = msg.caption or ""
                    if caption_template and (msg.document or msg.video or msg.photo or msg.audio):
                        fname = ""
                        fsize = ""
                        if msg.document:
                            fname = msg.document.file_name or "document"
                            fsize = f"{round(msg.document.file_size / (1024*1024), 2)} MB"
                        elif msg.video:
                            fname = msg.video.file_name or "video.mp4"
                            fsize = f"{round(msg.video.file_size / (1024*1024), 2)} MB"
                        elif msg.audio:
                            fname = msg.audio.file_name or "audio.mp3"
                            fsize = f"{round(msg.audio.file_size / (1024*1024), 2)} MB"
                            
                        try:
                            new_caption = caption_template.format(
                                filename=fname,
                                size=fsize,
                                caption=msg.caption or ""
                            )
                        except Exception:
                            new_caption = msg.caption or ""
                            
                    # Remove Words filters
                    if remove_words:
                        for word in remove_words:
                            if new_caption:
                                new_caption = new_caption.replace(word, "")
                                
                    # Send message copy or forward tag with robust FloodWait retry loop
                    max_retries = 3
                    retry_count = 0
                    sent_successfully = False
                    
                    while retry_count < max_retries and not sent_successfully:
                        if active_forwarding_tasks.get(user_id, {}).get("cancelled"):
                            break
                        try:
                            if filters.get("forward_tag", False):
                                # Forward (shows forwarded from header)
                                await client.forward_messages(chat_id=target_chat_id, from_chat_id=resolved_chat_id, message_ids=msg.id)
                            else:
                                # Copy (strips forward tag)
                                if msg.text:
                                    text_content = msg.text
                                    if remove_words:
                                        for word in remove_words:
                                            text_content = text_content.replace(word, "")
                                        await client.send_message(chat_id=target_chat_id, text=text_content)
                                    else:
                                        await client.copy_message(chat_id=target_chat_id, from_chat_id=resolved_chat_id, message_id=msg.id)
                                else:
                                    if new_caption:
                                        await client.copy_message(chat_id=target_chat_id, from_chat_id=resolved_chat_id, message_id=msg.id, caption=new_caption)
                                    else:
                                        await client.copy_message(chat_id=target_chat_id, from_chat_id=resolved_chat_id, message_id=msg.id)
                            stats["forwarded"] += 1
                            sent_successfully = True
                        except Exception as fe:
                            classname = fe.__class__.__name__
                            if classname == "FloodWait":
                                sleep_dur = getattr(fe, "value", 10)
                                retry_count += 1
                                logger.warning(f"FloodWait hit on message {msg.id}! Sleeping for {sleep_dur} seconds (attempt {retry_count}/{max_retries}).")
                                stats["status"] = f"FloodWait ({sleep_dur}s)"
                                update_status_message()
                                await asyncio.sleep(sleep_dur)
                                stats["status"] = "Forwarding"
                                update_status_message()
                            else:
                                logger.error(f"Failed to forward message {msg.id}: {fe}")
                                stats["skipped"] += 1
                                break
                except Exception as fe:
                    logger.error(f"Failed to process or forward message {msg.id}: {fe}")
                    stats["skipped"] += 1
                    
                update_status_message(is_done=(count == total))
                await asyncio.sleep(1.5)
                
            await client.disconnect()
        except Exception as ce:
            logger.error(f"Pyrogram forwarding execution crash: {ce}")
            stats["status"] = f"Crash: {str(ce)[:30]}"
            update_status_message(is_done=True)
            try:
                await client.disconnect()
            except:
                pass
                
        active_forwarding_tasks.pop(user_id, None)

# Default Configurations
DEFAULT_BUTTON_MESSAGES = {
    "user_help": (
        "📚 <b>Help Menu</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "Here are the instructions on how to use the bot:\n"
        "1. Connect your source channels using Settings.\n"
        "2. Configure forward filters for custom keywords.\n"
        "3. Enable status reporting to track deliveries.\n\n"
        "Need further assistance? Contact support at @AdminSupport."
    ),
    "user_about": (
        "ℹ️ <b>About This Bot</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "This is an <b>Advanced Forward Bot</b> designed to mirror and redirect content between chats with customization filters.\n\n"
        "• Version: <code>v2.1.0</code>\n"
        "• Engine: <code>pyTelegramBotAPI</code>\n"
        "• Features: Instant delivery, regex filters, caption editor."
    ),
    "user_settings": (
        "⚙️ <b>Bot Settings</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "Configure your bot parameters below:\n"
        "• Delay: <code>Disabled (Instant)</code>\n"
        "• Anti-Spam: <code>Active</code>\n"
        "• Forward Signature: <code>Off</code>\n\n"
        "<i>To change settings, use the /settings chat command.</i>"
    ),
    "user_status": (
        "📊 <b>System Status</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "• Bot Server: 🟢 <code>ONLINE</code>\n"
        "• Database Conn: 🟢 <code>CONNECTED</code>\n"
        "• Processed Jobs: <code>1,245 forwards</code>\n"
        "• Memory Usage: <code>45 MB</code>"
    ),
    "user_how_to_use": (
        "🔗 <b>How to Use Guide</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "Check out our interactive tutorial:\n"
        "1. Add the bot to your target channel as Admin.\n"
        "2. Send the channel ID or link to the bot.\n"
        "3. Use the forwarding wizard to link source and destination.\n\n"
        "Read the complete guide on GitHub: <a href='https://github.com'>Advanced-Forward-Bot-Wiki</a>"
    )
}

DEFAULT_CONFIG = {
    "bot_token": "YOUR_BOT_TOKEN_HERE",
    "admin_ids": [],
    "welcome_text": (
        "✨ HI {name} WELCOME TO OUR BOT 👋\n"
        "<blockquote>🎯 <b>I'M AN ADVANCED FORWARD BOT WITH SPECIAL FEATURES</b>\n\n"
        "⚡ <i>CLICK THE BUTTONS BELOW TO EXPLORE MORE</i></blockquote>"
    ),
    "welcome_photo": "https://picsum.photos/800/500",  # High quality random placeholder
    "button_messages": DEFAULT_BUTTON_MESSAGES
}

# --- CONFIG MANAGEMENT (Database Backed) ---
def load_config():
    """Loads configuration from settings table, creating it with defaults if not exists."""
    row = db.execute_query("SELECT value FROM settings WHERE key = %s", ("config",), fetch="one")
    if not row:
        try:
            val = json.dumps(DEFAULT_CONFIG, ensure_ascii=False)
            db.execute_query("INSERT INTO settings (key, value) VALUES (%s, %s)", ("config", val), commit=True)
            logger.info("Created default configuration in database settings.")
            return DEFAULT_CONFIG
        except Exception as e:
            logger.error(f"Error creating default config in DB: {e}")
            return DEFAULT_CONFIG
    
    try:
        config = json.loads(row[0])
        # Ensure all keys exist
        updated = False
        for k, v in DEFAULT_CONFIG.items():
            if k not in config:
                config[k] = v
                updated = True
            
        # Ensure button messages exist
        if "button_messages" not in config:
            config["button_messages"] = DEFAULT_CONFIG["button_messages"]
            updated = True
        else:
            for kb, vb in DEFAULT_CONFIG["button_messages"].items():
                if kb not in config["button_messages"]:
                    config["button_messages"][kb] = vb
                    updated = True
                        
        # Fix welcome message default text if it has no blockquote and is still using the old default
        old_default_match = "✨ HI {name} WELCOME TO OUR BOT 👋\n\n🎯 <b>I'M AN ADVANCED FORWARD BOT"
        if config.get("welcome_text", "").startswith(old_default_match):
            config["welcome_text"] = DEFAULT_CONFIG["welcome_text"]
            updated = True
                
        if updated:
            save_config(config)
        return config
    except Exception as e:
        logger.error(f"Error reading config from DB: {e}. Using defaults.")
        return DEFAULT_CONFIG

def save_config(config):
    """Saves configuration back to settings table."""
    try:
        val = json.dumps(config, ensure_ascii=False)
        row = db.execute_query("SELECT value FROM settings WHERE key = %s", ("config",), fetch="one")
        if row:
            db.execute_query("UPDATE settings SET value = %s WHERE key = %s", (val, "config"), commit=True)
        else:
            db.execute_query("INSERT INTO settings (key, value) VALUES (%s, %s)", ("config", val), commit=True)
        logger.info("Configuration saved successfully to Database settings.")
        return True
    except Exception as e:
        logger.error(f"Error saving config to DB: {e}")
        return False

# Initialize Config
config = load_config()

# Validate and Resolve Token
# Check common environment variables first, then fallback to config.json
TOKEN = (
    os.environ.get("BOT_TOKEN") or 
    os.environ.get("TELEGRAM_BOT_TOKEN") or 
    os.environ.get("TELEGRAM_TOKEN") or 
    os.environ.get("TOKEN") or 
    config.get("bot_token")
)

# Clean/strip token
if TOKEN:
    TOKEN = TOKEN.strip()

# Resolve Admin IDs from env
env_admins = os.environ.get("ADMIN_IDS")
if env_admins:
    try:
        # Expecting comma-separated numbers, e.g. "123456,789012"
        parsed_admins = [int(x.strip()) for x in env_admins.split(",") if x.strip().isdigit()]
        if parsed_admins:
            config["admin_ids"] = list(set(config.get("admin_ids", []) + parsed_admins))
            logger.info(f"Loaded admin IDs from environment: {parsed_admins}")
    except Exception as e:
        logger.error(f"Error parsing ADMIN_IDS environment variable: {e}")

# Validate Token format before initializing telebot
if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE" or ":" not in TOKEN:
    logger.critical("❌ ERROR: Bot Token is missing or invalid!")
    print("\n" + "="*80)
    print("CRITICAL CONFIGURATION ERROR:")
    print("Your Telegram Bot Token is not set or is invalid.")
    print("We checked environment variables (BOT_TOKEN, TELEGRAM_BOT_TOKEN, TOKEN) and config.json.")
    print("Please set the 'BOT_TOKEN' environment variable in your Railway variables.")
    print("="*80 + "\n")
    raise ValueError("Missing or invalid Bot Token. Please configure the BOT_TOKEN environment variable.")

# Initialize Bot
bot = telebot.TeleBot(TOKEN, parse_mode=None)

# Multi-user state storage for Admin edits
# format: { user_id: 'WAITING_FOR_TEXT' | 'WAITING_FOR_PHOTO' }
user_states = {}

# --- HELPER FUNCTIONS ---
def is_admin(user_id):
    """Checks if a user ID is listed in the admin list."""
    return user_id in config.get("admin_ids", [])

def format_welcome_message(text, user):
    """Substitutes user variables in the welcome message."""
    first_name = user.first_name if user.first_name else "User"
    username = f"@{user.username}" if user.username else first_name
    return text.format(
        name=first_name,
        username=username,
        id=user.id
    )

def parse_telegram_link(text):
    """
    Robust Telegram link parser.
    Supports message links (e.g. t.me/c/12345/678, t.me/mychat/678)
    and chat/channel links (e.g. t.me/c/12345, t.me/mychat).
    Returns (source_id, source_title).
    """
    import re
    cleaned = text.strip()
    
    # 1. Check message link first (e.g., t.me/mygroup/1234 or t.me/c/123456/123)
    match_msg = re.search(r"(?:t\.me|telegram\.me|telegram\.dog)/(?:c/)?([^/?#]+)/(\d+)", cleaned)
    if match_msg:
        chat_identifier = match_msg.group(1)
        is_private = "/c/" in cleaned
        if is_private:
            try:
                return int(f"-100{chat_identifier}"), "private"
            except ValueError:
                return f"@{chat_identifier}", f"@{chat_identifier}"
        else:
            if chat_identifier.isdigit():
                return int(chat_identifier), f"Chat {chat_identifier}"
            return f"@{chat_identifier}", f"@{chat_identifier}"
            
    # 2. Check chat link (e.g., t.me/mygroup or t.me/c/123456)
    match_chat = re.search(r"(?:t\.me|telegram\.me|telegram\.dog)/(?:c/)?([^/?#]+)", cleaned)
    if match_chat:
        chat_identifier = match_chat.group(1)
        # Exclude bot commands like /start or /cancel
        if chat_identifier.startswith("/") or chat_identifier.lower() in ["start", "cancel", "admin", "myid", "forward"]:
            return None, None
        is_private = "/c/" in cleaned
        if is_private:
            try:
                return int(f"-100{chat_identifier}"), "private"
            except ValueError:
                return f"@{chat_identifier}", f"@{chat_identifier}"
        else:
            if chat_identifier.isdigit():
                return int(chat_identifier), f"Chat {chat_identifier}"
            return f"@{chat_identifier}", f"@{chat_identifier}"
            
    return None, None

def check_client_source_access(user_id, source_id):
    """
    Checks if the linked userbot or custom bot has access to the source chat.
    Returns (is_accessible, error_message, resolved_title).
    """
    bot_row = db.execute_query("SELECT bot_token, bot_name FROM linked_bots WHERE user_id = %s ORDER BY id DESC", (user_id,), fetch="one")
    ub_row = db.execute_query("SELECT session_string, phone FROM linked_userbots WHERE user_id = %s ORDER BY id DESC", (user_id,), fetch="one")
    
    if not bot_row and not ub_row:
        return False, "❌ No linked bots or userbots found. Please add a bot or userbot in Settings first.", None

    is_simulation = True
    has_real_userbot = ub_row and ub_row[0] and not ub_row[0].startswith("SIMULATED")
    has_real_bot = bot_row and bot_row[0] and bot_row[0] != "YOUR_BOT_TOKEN_HERE" and not bot_row[0].startswith("SIMULATED")
    if has_real_userbot or has_real_bot:
        is_simulation = False

    if is_simulation:
        resolved_title = "Simulated Source Chat"
        if isinstance(source_id, int):
            resolved_title = f"Simulated Group ({source_id})"
        elif isinstance(source_id, str):
            resolved_title = source_id
        return True, None, resolved_title

    # 1. Check via Userbot (Pyrogram) if available
    if ub_row and ub_row[0]:
        session = ub_row[0]
        API_ID = os.environ.get("API_ID") or config.get("api_id")
        API_HASH = os.environ.get("API_HASH") or config.get("api_hash")
        
        if PYROGRAM_AVAILABLE and API_ID and API_HASH:
            async def do_check():
                client = Client(
                    name=f"temp_check_{user_id}",
                    api_id=int(API_ID),
                    api_hash=API_HASH,
                    session_string=session,
                    in_memory=True
                )
                try:
                    await client.connect()
                    
                    # Populate peer database cache for numeric IDs
                    try:
                        async for dialog in client.get_dialogs(limit=100):
                            pass
                    except Exception as e:
                        logger.warning(f"Failed to fetch dialogs in access check: {e}")
                    
                    try:
                        chat = await client.get_chat(source_id)
                        title = chat.title or chat.first_name or "Private Source"
                        return True, None, title
                    except Exception as e:
                        err_str = str(e)
                        if "USER_DEACTIVATED" in err_str:
                            return False, "❌ The userbot account has been deactivated.", None
                        elif "SESSION_EXPIRED" in err_str:
                            return False, "❌ The userbot session has expired. Please re-authenticate.", None
                        else:
                            return False, f"❌ Userbot cannot access the source chat: {err_str}", None
                    finally:
                        try:
                            await client.disconnect()
                        except:
                            pass
                except Exception as e:
                    return False, f"❌ Failed to connect userbot client: {e}", None
                    
            try:
                success, err, title = run_async(do_check())
                return success, err, title
            except Exception as e:
                return False, f"❌ Error running access check: {e}", None

    # 2. Check via Custom Bot if userbot not linked
    if bot_row and bot_row[0]:
        token = bot_row[0]
        import requests
        try:
            res = requests.get(f"https://api.telegram.org/bot{token}/getChat", params={"chat_id": source_id}, timeout=10)
            data = res.json()
            if data.get("ok"):
                chat = data["result"]
                title = chat.get("title") or chat.get("username") or "Source Chat"
                return True, None, title
            else:
                desc = data.get("description", "")
                if "chat not found" in desc.lower():
                    return False, "❌ Custom bot is not added to the source chat, or the chat ID/link is invalid.", None
                return False, f"❌ Custom bot access check failed: {desc}", None
        except Exception as e:
            return False, f"❌ HTTP error checking custom bot access: {e}", None

    return False, "❌ No active bot or userbot available to verify access.", None

# --- KEYBOARDS ---
def get_user_welcome_markup(user_id):
    """Returns the welcome inline keyboard shown in the screenshot."""
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📚 Help", callback_data="user_help"),
        InlineKeyboardButton("ℹ️ About", callback_data="user_about")
    )
    markup.row(
        InlineKeyboardButton("⚙️ Settings", callback_data="user_settings"),
        InlineKeyboardButton("📊 Status", callback_data="user_status")
    )
    markup.row(
        InlineKeyboardButton("🔗 How to Use", callback_data="user_how_to_use")
    )
    
    # If the user is an admin, add a quick shortcut to the Admin Control Panel
    if is_admin(user_id):
        markup.row(
            InlineKeyboardButton("👑 Admin Panel", callback_data="admin_menu")
        )
    return markup

def get_admin_panel_markup():
    """Returns the main admin control panel inline keyboard."""
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("🏠 Intro Panel Settings", callback_data="admin_intro_menu"),
        InlineKeyboardButton("🔘 Button Response Messages", callback_data="admin_buttons_menu")
    )
    markup.row(
        InlineKeyboardButton("👁️ Preview Welcome", callback_data="admin_preview"),
        InlineKeyboardButton("🏠 Open User View", callback_data="admin_user_view")
    )
    return markup

def get_admin_intro_markup():
    """Returns the intro panel configuration inline keyboard."""
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📝 Edit Intro Text", callback_data="admin_edit_text"),
        InlineKeyboardButton("🖼️ Edit Intro Photo", callback_data="admin_edit_photo")
    )
    markup.add(InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_menu"))
    return markup

def get_admin_buttons_markup():
    """Returns the inline keyboard for editing response messages for user buttons."""
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📚 Help Message", callback_data="admin_edit_btn_user_help"),
        InlineKeyboardButton("ℹ️ About Message", callback_data="admin_edit_btn_user_about")
    )
    markup.row(
        InlineKeyboardButton("⚙️ Settings Message", callback_data="admin_edit_btn_user_settings"),
        InlineKeyboardButton("📊 Status Message", callback_data="admin_edit_btn_user_status")
    )
    markup.row(
        InlineKeyboardButton("🔗 Edit How to Use Msg", callback_data="admin_edit_btn_user_how_to_use")
    )
    markup.add(InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_menu"))
    return markup

def get_cancel_markup():
    """Returns a cancel button for admin operations."""
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel"))
    return markup

def get_settings_markup():
    """Returns the settings panel keyboard layout as requested by the user."""
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("🤖 Bots", callback_data="settings_bots"),
        InlineKeyboardButton("🏷️ Channels", callback_data="settings_channels")
    )
    markup.row(
        InlineKeyboardButton("🖊️ Caption", callback_data="settings_caption"),
        InlineKeyboardButton("🔲 Button", callback_data="settings_button")
    )
    markup.row(
        InlineKeyboardButton("🕵️ Filters 🕵️", callback_data="settings_filters")
    )
    markup.row(
        InlineKeyboardButton("🚫 Remove Words", callback_data="settings_remove_words")
    )
    markup.row(
        InlineKeyboardButton("Extra Settings 🧪", callback_data="settings_extra")
    )
    markup.row(
        InlineKeyboardButton("◀️ Back", callback_data="settings_back")
    )
    return markup

def show_settings_panel(call):
    """Transition from welcome panel to Settings Panel by editing the caption and buttons in place."""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    settings_text = (
        "<b>HERE IS THE SETTINGS PANEL⚙️</b>\n\n"
        "<b>CHANGE YOUR SETTINGS AS YOUR WISH👇</b>"
    )
    markup = get_settings_markup()
    
    # Determine if message has photo
    has_photo = call.message.content_type == "photo" or (hasattr(call.message, 'photo') and call.message.photo is not None)
    
    if has_photo:
        try:
            bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=settings_text,
                reply_markup=markup,
                parse_mode="HTML"
            )
            return
        except Exception as e:
            logger.error(f"Error editing caption to settings panel: {e}")
            
    # Text fallback
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=settings_text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error editing text to settings panel: {e}")

def show_welcome_panel(call):
    """Transition from Settings Panel back to the Main Welcome panel by editing in place."""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user = call.from_user
    
    welcome_text = config.get("welcome_text", DEFAULT_CONFIG["welcome_text"])
    formatted_text = format_welcome_message(welcome_text, user)
    markup = get_user_welcome_markup(user.id)
    
    has_photo = call.message.content_type == "photo" or (hasattr(call.message, 'photo') and call.message.photo is not None)
    
    if has_photo:
        try:
            bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=formatted_text,
                reply_markup=markup,
                parse_mode="HTML"
            )
            return
        except Exception as e:
            logger.error(f"Error editing caption back to welcome panel: {e}")
            
    # Text fallback
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=formatted_text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error editing text back to welcome panel: {e}")

def get_bots_settings_markup(user_id):
    """Returns the keyboard layout for the Bots configuration submenu dynamically showing linked bots."""
    markup = InlineKeyboardMarkup()
    
    # Retrieve linked bots
    linked_bots = db.execute_query(
        "SELECT id, bot_name, bot_username FROM linked_bots WHERE user_id = %s",
        (user_id,), fetch="all"
    )
    # Retrieve linked userbots
    linked_userbots = db.execute_query(
        "SELECT id, phone, first_name, username FROM linked_userbots WHERE user_id = %s",
        (user_id,), fetch="all"
    )
    
    # If bots exist, show them. Otherwise show the add button.
    if linked_bots:
        for b_id, b_name, b_username in linked_bots:
            display_name = b_name if b_name else f"@{b_username}"
            markup.add(InlineKeyboardButton(display_name, callback_data=f"manage_bot_{b_id}"))
    else:
        markup.add(InlineKeyboardButton("➕ Add Bot ➕", callback_data="settings_bots_add"))
            
    # If userbots exist, show them. Otherwise show the add button.
    if linked_userbots:
        for u_id, phone, f_name, u_name in linked_userbots:
            display_name = f"@{u_name}" if u_name else (f_name if f_name else f"👤 Userbot ({phone})")
            markup.add(InlineKeyboardButton(display_name, callback_data=f"manage_userbot_{u_id}"))
    else:
        markup.add(InlineKeyboardButton("➕ Add User bot ➕", callback_data="settings_bots_userbot"))
            
    # Back button on its own row
    markup.add(InlineKeyboardButton("back", callback_data="settings_menu"))
    return markup

def show_bots_settings_panel(call):
    """Transition from Settings Panel to Bots Settings Panel by editing in place."""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user_id = call.from_user.id
    
    text = "<u>My Bots</u>\n\nYou can manage your bots in here"
    markup = get_bots_settings_markup(user_id)
    
    has_photo = call.message.content_type == "photo" or (hasattr(call.message, 'photo') and call.message.photo is not None)
    
    if has_photo:
        try:
            bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=text,
                reply_markup=markup,
                parse_mode="HTML"
            )
            return
        except Exception as e:
            logger.error(f"Error editing caption to bots settings panel: {e}")
            
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error editing text to bots settings panel: {e}")

def send_bots_settings_panel(chat_id, user_id=None):
    """Sends the Bots configuration panel as a new message (used after text-based input flows)."""
    if user_id is None:
        user_id = chat_id  # in private chats, chat_id equals user_id
    welcome_photo = config.get("welcome_photo", DEFAULT_CONFIG["welcome_photo"])
    text = "<u>My Bots</u>\n\nYou can manage your bots in here"
    markup = get_bots_settings_markup(user_id)
    if welcome_photo:
        try:
            bot.send_photo(chat_id, welcome_photo, caption=text, reply_markup=markup, parse_mode="HTML")
            return
        except Exception as e:
            logger.error(f"Error sending photo for bots settings: {e}")
            
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

def show_bot_details_panel(call, bot_id):
    """Transition to Bot Details panel where user can view and remove the bot."""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    row = db.execute_query(
        "SELECT id, bot_name, bot_username, bot_telegram_id FROM linked_bots WHERE id = %s",
        (bot_id,), fetch="one"
    )
    if not row:
        bot.answer_callback_query(call.id, "❌ Bot not found.", show_alert=True)
        show_bots_settings_panel(call)
        return
        
    b_id, b_name, b_username, b_tel_id = row
    
    text = (
        "🤖 <b>BOT DETAILS</b>\n\n"
        "<blockquote>"
        f"📝 <b>NAME:</b> {b_name}\n"
        f"🆔 <b>BOT ID:</b> {b_tel_id}\n"
        f"👤 <b>USERNAME:</b> @{b_username}"
        "</blockquote>"
    )
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ Remove ❌", callback_data=f"remove_bot_{b_id}"))
    markup.add(InlineKeyboardButton("back", callback_data="settings_bots"))
    
    has_photo = call.message.content_type == "photo" or (hasattr(call.message, 'photo') and call.message.photo is not None)
    
    if has_photo:
        try:
            bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=text,
                reply_markup=markup,
                parse_mode="HTML"
            )
            return
        except Exception as e:
            logger.error(f"Error editing caption to bot details: {e}")
            
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error editing text to bot details: {e}")

def show_userbot_details_panel(call, u_id):
    """Transition to Userbot Details panel where user can view and remove the userbot."""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    row = db.execute_query(
        "SELECT id, phone, user_id FROM linked_userbots WHERE id = %s",
        (u_id,), fetch="one"
    )
    if not row:
        bot.answer_callback_query(call.id, "❌ Userbot not found.", show_alert=True)
        show_bots_settings_panel(call)
        return
        
    u_id_db, phone, tg_id = row
    
    text = (
        "👤 <b>USERBOT DETAILS</b>\n\n"
        "<blockquote>"
        f"📞 <b>PHONE:</b> {phone}\n"
        f"🆔 <b>USER ID:</b> {tg_id}"
        "</blockquote>"
    )
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ Remove ❌", callback_data=f"remove_userbot_{u_id_db}"))
    markup.add(InlineKeyboardButton("back", callback_data="settings_bots"))
    
    has_photo = call.message.content_type == "photo" or (hasattr(call.message, 'photo') and call.message.photo is not None)
    
    if has_photo:
        try:
            bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=text,
                reply_markup=markup,
                parse_mode="HTML"
            )
            return
        except Exception as e:
            logger.error(f"Error editing caption to userbot details: {e}")
            
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error editing text to userbot details: {e}")

def get_channels_settings_markup(user_id):
    """Returns the keyboard layout for the Channels configuration submenu."""
    markup = InlineKeyboardMarkup()
    
    # Retrieve linked target chats
    target_chats = db.execute_query(
        "SELECT id, chat_title FROM target_chats WHERE user_id = %s",
        (user_id,), fetch="all"
    )
    
    # Add buttons for each target chat
    if target_chats:
        for c_id, c_title in target_chats:
            markup.add(InlineKeyboardButton(c_title, callback_data=f"manage_channel_{c_id}"))
            
    # Add control button
    markup.add(InlineKeyboardButton("➕ Add Channel ➕", callback_data="settings_channels_add"))
    
    # Back button
    markup.add(InlineKeyboardButton("back", callback_data="settings_menu"))
    return markup

def show_channels_settings_panel(call):
    """Transition to Channels Settings Panel by editing in place."""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user_id = call.from_user.id
    
    text = "<b><u>My Channels</u></b>\n\nyou can manage your target chats in here"
    markup = get_channels_settings_markup(user_id)
    
    has_photo = call.message.content_type == "photo" or (hasattr(call.message, 'photo') and call.message.photo is not None)
    
    if has_photo:
        try:
            bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=text,
                reply_markup=markup,
                parse_mode="HTML"
            )
            return
        except Exception as e:
            logger.error(f"Error editing caption to channels panel: {e}")
            
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error editing text to channels panel: {e}")

def send_channels_settings_panel(chat_id, user_id=None):
    """Sends the Channels settings panel as a new message (after text flows)."""
    if user_id is None:
        user_id = chat_id
    welcome_photo = config.get("welcome_photo", DEFAULT_CONFIG["welcome_photo"])
    text = "<b><u>My Channels</u></b>\n\nyou can manage your target chats in here"
    markup = get_channels_settings_markup(user_id)
    if welcome_photo:
        try:
            bot.send_photo(chat_id, welcome_photo, caption=text, reply_markup=markup, parse_mode="HTML")
            return
        except Exception as e:
            logger.error(f"Error sending photo for channels settings: {e}")
            
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

def show_channel_details_panel(call, c_id):
    """Transition to Channel Details panel where user can view and remove the target chat."""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    row = db.execute_query(
        "SELECT id, chat_title, chat_id, chat_username FROM target_chats WHERE id = %s",
        (c_id,), fetch="one"
    )
    if not row:
        bot.answer_callback_query(call.id, "❌ Channel not found.", show_alert=True)
        show_channels_settings_panel(call)
        return
        
    c_id_db, c_title, c_chat_id, c_username = row
    
    username_text = f"@{c_username}" if c_username else "None"
    text = (
        "🏷️ <b>CHANNEL DETAILS</b>\n\n"
        "<blockquote>"
        f"📝 <b>TITLE:</b> {c_title}\n"
        f"🆔 <b>CHAT ID:</b> {c_chat_id or 'Pending'}\n"
        f"👤 <b>USERNAME:</b> {username_text}"
        "</blockquote>"
    )
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ Remove ❌", callback_data=f"remove_channel_{c_id_db}"))
    markup.add(InlineKeyboardButton("back", callback_data="settings_channels"))
    
    has_photo = call.message.content_type == "photo" or (hasattr(call.message, 'photo') and call.message.photo is not None)
    
    if has_photo:
        try:
            bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=text,
                reply_markup=markup,
                parse_mode="HTML"
            )
            return
        except Exception as e:
            logger.error(f"Error editing caption to channel details: {e}")
            
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error editing text to channel details: {e}")

def show_caption_settings_panel(call):
    """Transition to Custom Caption Settings panel."""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user_id = call.from_user.id
    
    settings = get_user_settings(user_id)
    curr_caption = settings.get("custom_caption")
    caption_status = f"<code>{curr_caption}</code>" if curr_caption else "<i>Not Set (Default Caption)</i>"
    
    text = (
        "<b><u>CUSTOM CAPTION</u></b>\n\n"
        "You can set a custom caption to videos and documents. Normaly use its default caption\n\n"
        f"<b>Current Caption:</b>\n{caption_status}\n\n"
        "<b>AVAILABLE FILLINGS:</b>\n"
        "- <code>{filename}</code> : Filename\n"
        "- <code>{size}</code> : File size\n"
        "- <code>{caption}</code> : default caption"
    )
    
    markup = InlineKeyboardMarkup()
    if curr_caption:
        markup.row(
            InlineKeyboardButton("🖊️ Edit Caption 🖊️", callback_data="settings_caption_add"),
            InlineKeyboardButton("❌ Remove Caption ❌", callback_data="settings_caption_remove")
        )
    else:
        markup.add(InlineKeyboardButton("➕ Add Caption ➕", callback_data="settings_caption_add"))
    markup.add(InlineKeyboardButton("back", callback_data="settings_menu"))
    
    has_photo = call.message.content_type == "photo" or (hasattr(call.message, 'photo') and call.message.photo is not None)
    
    if has_photo:
        try:
            bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=text, reply_markup=markup, parse_mode="HTML")
            return
        except Exception as e:
            logger.error(f"Error editing caption: {e}")
            
    try:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error editing text: {e}")

def send_caption_settings_panel(chat_id, user_id=None):
    if user_id is None:
        user_id = chat_id
    welcome_photo = config.get("welcome_photo", DEFAULT_CONFIG["welcome_photo"])
    
    settings = get_user_settings(user_id)
    curr_caption = settings.get("custom_caption")
    caption_status = f"<code>{curr_caption}</code>" if curr_caption else "<i>Not Set (Default Caption)</i>"
    
    text = (
        "<b><u>CUSTOM CAPTION</u></b>\n\n"
        "You can set a custom caption to videos and documents. Normaly use its default caption\n\n"
        f"<b>Current Caption:</b>\n{caption_status}\n\n"
        "<b>AVAILABLE FILLINGS:</b>\n"
        "- <code>{filename}</code> : Filename\n"
        "- <code>{size}</code> : File size\n"
        "- <code>{caption}</code> : default caption"
    )
    
    markup = InlineKeyboardMarkup()
    if curr_caption:
        markup.row(
            InlineKeyboardButton("🖊️ Edit Caption 🖊️", callback_data="settings_caption_add"),
            InlineKeyboardButton("❌ Remove Caption ❌", callback_data="settings_caption_remove")
        )
    else:
        markup.add(InlineKeyboardButton("➕ Add Caption ➕", callback_data="settings_caption_add"))
    markup.add(InlineKeyboardButton("back", callback_data="settings_menu"))
    
    if welcome_photo:
        try:
            bot.send_photo(chat_id, welcome_photo, caption=text, reply_markup=markup, parse_mode="HTML")
            return
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
            
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

def get_filters_markup(user_id, page=1):
    markup = InlineKeyboardMarkup()
    settings = get_user_settings(user_id)
    filters = settings.get("filters", {})
    
    def get_emoji(val):
        return "✅" if val else "❌"
        
    if page == 1:
        # 🏷️ Forward tag
        f_tag = filters.get("forward_tag", False)
        markup.row(
            InlineKeyboardButton("🏷️ Forward tag", callback_data="toggle_filter_forward_tag_1"),
            InlineKeyboardButton(get_emoji(f_tag), callback_data="toggle_filter_forward_tag_1")
        )
        # 🖍️ Texts
        txts = filters.get("texts", True)
        markup.row(
            InlineKeyboardButton("🖍️ Texts", callback_data="toggle_filter_texts_1"),
            InlineKeyboardButton(get_emoji(txts), callback_data="toggle_filter_texts_1")
        )
        # 📁 Documents
        docs = filters.get("documents", True)
        markup.row(
            InlineKeyboardButton("📁 Documents", callback_data="toggle_filter_documents_1"),
            InlineKeyboardButton(get_emoji(docs), callback_data="toggle_filter_documents_1")
        )
        # 🎬 Videos
        vids = filters.get("videos", True)
        markup.row(
            InlineKeyboardButton("🎬 Videos", callback_data="toggle_filter_videos_1"),
            InlineKeyboardButton(get_emoji(vids), callback_data="toggle_filter_videos_1")
        )
        # 📷 Photos
        imgs = filters.get("photos", True)
        markup.row(
            InlineKeyboardButton("📷 Photos", callback_data="toggle_filter_photos_1"),
            InlineKeyboardButton(get_emoji(imgs), callback_data="toggle_filter_photos_1")
        )
        # 🎧 Audios
        auds = filters.get("audios", True)
        markup.row(
            InlineKeyboardButton("🎧 Audios", callback_data="toggle_filter_audios_1"),
            InlineKeyboardButton(get_emoji(auds), callback_data="toggle_filter_audios_1")
        )
        
        markup.row(
            InlineKeyboardButton("≪ back", callback_data="settings_menu"),
            InlineKeyboardButton("next ≫", callback_data="settings_filters_page_2")
        )
    else:
        # 🎤 Voices
        vcs = filters.get("voices", True)
        markup.row(
            InlineKeyboardButton("🎤 Voices", callback_data="toggle_filter_voices_2"),
            InlineKeyboardButton(get_emoji(vcs), callback_data="toggle_filter_voices_2")
        )
        # 🎭 Animations
        anms = filters.get("animations", True)
        markup.row(
            InlineKeyboardButton("🎭 Animations", callback_data="toggle_filter_animations_2"),
            InlineKeyboardButton(get_emoji(anms), callback_data="toggle_filter_animations_2")
        )
        # 🃏 Stickers
        stks = filters.get("stickers", True)
        markup.row(
            InlineKeyboardButton("🃏 Stickers", callback_data="toggle_filter_stickers_2"),
            InlineKeyboardButton(get_emoji(stks), callback_data="toggle_filter_stickers_2")
        )
        # ▶️ Skip duplicate
        skps = filters.get("skip_duplicate", True)
        markup.row(
            InlineKeyboardButton("▶️ Skip duplicate", callback_data="toggle_filter_skip_duplicate_2"),
            InlineKeyboardButton(get_emoji(skps), callback_data="toggle_filter_skip_duplicate_2")
        )
        # 📊 Poll
        plls = filters.get("poll", True)
        markup.row(
            InlineKeyboardButton("📊 Poll", callback_data="toggle_filter_poll_2"),
            InlineKeyboardButton(get_emoji(plls), callback_data="toggle_filter_poll_2")
        )
        # 🔒 Secure message
        scrs = filters.get("secure_message", False)
        markup.row(
            InlineKeyboardButton("🔒 Secure message", callback_data="toggle_filter_secure_message_2"),
            InlineKeyboardButton(get_emoji(scrs), callback_data="toggle_filter_secure_message_2")
        )
        
        markup.row(
            InlineKeyboardButton("≪ back", callback_data="settings_filters_page_1"),
            InlineKeyboardButton("End ≫", callback_data="settings_menu")
        )
        
    return markup

def show_filters_settings_panel(call, page=1):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user_id = call.from_user.id
    
    text = (
        "<b>💠 CUSTOM FILTERS 💠</b>\n\n"
        "<b>configure the type of messages which you want forward</b>"
    )
    markup = get_filters_markup(user_id, page)
    
    has_photo = call.message.content_type == "photo" or (hasattr(call.message, 'photo') and call.message.photo is not None)
    
    if has_photo:
        try:
            bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=text, reply_markup=markup, parse_mode="HTML")
            return
        except Exception as e:
            logger.error(f"Error editing caption: {e}")
            
    try:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error editing text: {e}")

def get_remove_words_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ Add Remove Word", callback_data="remove_words_add"))
    markup.add(InlineKeyboardButton("➖ Delete Remove Word", callback_data="remove_words_delete"))
    markup.add(InlineKeyboardButton("📋 View Remove Words List", callback_data="remove_words_view"))
    markup.add(InlineKeyboardButton("🗑️ Clear All Remove Words", callback_data="remove_words_clear"))
    markup.add(InlineKeyboardButton("◀️ Back to Settings", callback_data="settings_menu"))
    return markup

def show_remove_words_settings_panel(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user_id = call.from_user.id
    
    settings = get_user_settings(user_id)
    words = settings.get("remove_words", [])
    words_list = ", ".join([f"<code>{w}</code>" for w in words]) if words else "<i>None</i>"
    
    text = (
        "<b>🚫 Remove Words Settings</b>\n\n"
        "Here you can manage words to remove from post captions.\n\n"
        f"<b>Active Remove Words:</b> {words_list}"
    )
    markup = get_remove_words_markup()
    
    has_photo = call.message.content_type == "photo" or (hasattr(call.message, 'photo') and call.message.photo is not None)
    
    if has_photo:
        try:
            bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=text, reply_markup=markup, parse_mode="HTML")
            return
        except Exception as e:
            logger.error(f"Error editing caption: {e}")
            
    try:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error editing text: {e}")

def send_remove_words_settings_panel(chat_id, user_id=None):
    if user_id is None:
        user_id = chat_id
    welcome_photo = config.get("welcome_photo", DEFAULT_CONFIG["welcome_photo"])
    
    settings = get_user_settings(user_id)
    words = settings.get("remove_words", [])
    words_list = ", ".join([f"<code>{w}</code>" for w in words]) if words else "<i>None</i>"
    
    text = (
        "<b>🚫 Remove Words Settings</b>\n\n"
        "Here you can manage words to remove from post captions.\n\n"
        f"<b>Active Remove Words:</b> {words_list}"
    )
    markup = get_remove_words_markup()
    
    if welcome_photo:
        try:
            bot.send_photo(chat_id, welcome_photo, caption=text, reply_markup=markup, parse_mode="HTML")
            return
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
            
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

def show_admin_intro_menu(chat_id):
    welcome_photo = config.get("welcome_photo", "None")
    welcome_text = config.get("welcome_text", "")
    
    admin_msg = (
        "🏠 <b>INTRO PANEL CONFIGURATION</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Manage the welcome text and image shown to users on /start.\n\n"
        f"🖼️ <b>Current Photo:</b>\n"
        f"<code>{welcome_photo[:60] + '...' if len(str(welcome_photo)) > 60 else welcome_photo}</code>\n\n"
        f"📝 <b>Current Text:</b>\n"
        f"{welcome_text}\n\n"
        "💡 Use the buttons below to modify:"
    )
    bot.send_message(chat_id, admin_msg, reply_markup=get_admin_intro_markup(), parse_mode="HTML")

def show_admin_buttons_menu(chat_id):
    btn_msg = (
        "🔘 <b>BUTTON RESPONSE MESSAGES</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Select a button below to configure the message sent when a user clicks it.\n"
        "All response messages support HTML formatting (bold, italic, quote, etc.)."
    )
    bot.send_message(chat_id, btn_msg, reply_markup=get_admin_buttons_markup(), parse_mode="HTML")

# --- CORE SENDER ---
def send_welcome_message(chat_id, user):
    """Sends the welcome image, text and buttons with robust exception fallback."""
    welcome_text = config.get("welcome_text", DEFAULT_CONFIG["welcome_text"])
    welcome_photo = config.get("welcome_photo", DEFAULT_CONFIG["welcome_photo"])
    
    formatted_text = format_welcome_message(welcome_text, user)
    markup = get_user_welcome_markup(user.id)
    
    # Check if a photo is set
    if welcome_photo:
        try:
            bot.send_photo(
                chat_id,
                welcome_photo,
                caption=formatted_text,
                reply_markup=markup,
                parse_mode="HTML"
            )
            logger.info(f"Sent photo welcome message to user {user.id}")
            return
        except Exception as e:
            logger.error(f"Failed to send photo welcome to {user.id}: {e}. Falling back to text-only.")
            # Fall through to text-only if photo fails
    
    # Text-only fallback
    try:
        bot.send_message(
            chat_id,
            formatted_text,
            reply_markup=markup,
            parse_mode="HTML"
        )
        logger.info(f"Sent text fallback welcome message to user {user.id}")
    except Exception as e:
        logger.critical(f"Failed to send welcome message entirely: {e}")

# --- COMMAND HANDLERS ---
@bot.message_handler(commands=["start"])
def cmd_start(message):
    """Handles the /start command."""
    user_id = message.from_user.id
    global config
    
    # Auto-admin feature: If admin list is empty, make the first user who starts the bot an admin
    if not config.get("admin_ids"):
        config["admin_ids"] = [user_id]
        save_config(config)
        bot.reply_to(
            message,
            f"👑 <b>Admin Set!</b>\n"
            f"Since no admins were configured, your ID (<code>{user_id}</code>) has been set as the main admin.",
            parse_mode="HTML"
        )
        logger.info(f"Auto-configured first user {user_id} as Admin.")
    
    # Send the premium welcome message
    send_welcome_message(message.chat.id, message.from_user)

@bot.message_handler(commands=["admin"])
def cmd_admin(message):
    """Handles the /admin command to launch the Admin Control Panel."""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.reply_to(
            message,
            f"❌ <b>Access Denied</b>\n\n"
            f"You are not authorized to access the Admin Panel.\n"
            f"Your Telegram User ID is: <code>{user_id}</code>\n\n"
            f"<i>To grant access, add your ID to the <code>admin_ids</code> array in <code>config.json</code>.</i>",
            parse_mode="HTML"
        )
        logger.warning(f"Unauthorized admin access attempt by User ID {user_id}")
        return
    
    admin_msg = (
        "👑 <b>ADMIN CONTROL PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Manage how your bot is displayed to users.\n\n"
        "💡 Select a module below to configure settings:"
    )
    
    bot.send_message(
        message.chat.id,
        admin_msg,
        reply_markup=get_admin_panel_markup(),
        parse_mode="HTML"
    )

@bot.message_handler(commands=["myid"])
def cmd_myid(message):
    """Quick utility command for users to find their own ID."""
    bot.reply_to(
        message,
        f"👤 <b>Your Telegram Details:</b>\n"
        f"• First Name: {message.from_user.first_name}\n"
        f"• Username: @{message.from_user.username if message.from_user.username else 'None'}\n"
        f"• User ID: <code>{message.from_user.id}</code>",
        parse_mode="HTML"
    )

@bot.message_handler(commands=["forward"])
def cmd_forward(message):
    """Initiates the forwarding wizard process."""
    user_id = message.from_user.id
    
    # Check if they have target chats configured first
    targets = db.execute_query("SELECT id FROM target_chats WHERE user_id = %s", (user_id,), fetch="all")
    if not targets:
        bot.reply_to(
            message,
            "❌ <b>No Target Channels Configured!</b>\n\n"
            "Please add at least one target channel/group in the Settings ➔ Channels menu first before initiating a forward.",
            parse_mode="HTML"
        )
        return
        
    # Check if they already have an active forwarding task running
    if user_id in active_forwarding_tasks:
        bot.reply_to(
            message,
            "❌ <b>Active Forwarding Task Already Running!</b>\n\n"
            "Please wait for the active forwarding task to complete or cancel it first.",
            parse_mode="HTML"
        )
        return
        
    user_states[user_id] = "WAITING_FOR_SOURCE_CHAT"
    
    text = (
        "📤 <b>SET SOURCE CHAT</b>\n\n"
        "<blockquote>"
        "FORWARD THE LAST MESSAGE OR LAST MESSAGE LINK OF SOURCE CHAT\n\n"
        "/cancel - CANCEL THIS PROCESS"
        "</blockquote>"
    )
    bot.send_message(message.chat.id, text, parse_mode="HTML")

# --- STATE-BASED MESSAGE HANDLER ---
@bot.message_handler(content_types=['text', 'photo', 'audio', 'document', 'video', 'video_note', 'voice', 'location', 'contact', 'sticker'], func=lambda msg: msg.from_user.id in user_states and user_states[msg.from_user.id] is not None)
def handle_admin_inputs(message):
    """Processes incoming text and media from admins based on active editing states."""
    user_id = message.from_user.id
    state = user_states.get(user_id)
    
    # Allow users to complete the custom bot/userbot wizards, but restrict introductory configs to admins
    if not is_admin(user_id) and state not in ["WAITING_FOR_BOT_TOKEN", "WAITING_FOR_PHONE", "WAITING_FOR_CODE", "WAITING_FOR_2FA", "WAITING_FOR_TARGET_CHAT", "WAITING_FOR_CUSTOM_CAPTION", "WAITING_FOR_REMOVE_WORD", "WAITING_FOR_DELETE_REMOVE_WORD", "WAITING_FOR_SOURCE_CHAT"]:
        user_states[user_id] = None
        return
        
    global config
    
    if state == "WAITING_FOR_TEXT":
        if not message.text:
            bot.reply_to(message, "❌ Please send text only for the welcome message.", reply_markup=get_cancel_markup())
            return
            
        config["welcome_text"] = message.text
        save_config(config)
        user_states[user_id] = None
        
        bot.reply_to(message, "✅ <b>Welcome Text Updated Successfully!</b>", parse_mode="HTML")
        show_admin_intro_menu(message.chat.id)
        
    elif state == "WAITING_FOR_PHOTO":
        # Check if the user sent a photo
        if message.photo:
            # Take the highest resolution photo file ID
            photo_id = message.photo[-1].file_id
            config["welcome_photo"] = photo_id
            save_config(config)
            user_states[user_id] = None
            
            bot.reply_to(message, "✅ <b>Welcome Photo Updated (using Telegram File ID)!</b>", parse_mode="HTML")
            show_admin_intro_menu(message.chat.id)
            
        # Check if they sent a text (assumed to be a URL)
        elif message.text:
            input_text = message.text.strip()
            # Basic validation
            if input_text.startswith("http://") or input_text.startswith("https://"):
                config["welcome_photo"] = input_text
                save_config(config)
                user_states[user_id] = None
                
                bot.reply_to(message, "✅ <b>Welcome Photo Updated (using URL)!</b>", parse_mode="HTML")
                show_admin_intro_menu(message.chat.id)
            else:
                bot.reply_to(
                    message, 
                    "❌ <b>Invalid Input</b>\n"
                    "Please upload a photo directly or send a valid URL starting with <code>http://</code> or <code>https://</code>.",
                    parse_mode="HTML",
                    reply_markup=get_cancel_markup()
                )
        else:
            bot.reply_to(message, "❌ Please upload a photo or send a photo URL.", reply_markup=get_cancel_markup())
            
    elif state == "WAITING_FOR_BOT_TOKEN":
        token = message.text.strip() if message.text else ""
        if not token or ":" not in token:
            bot.reply_to(
                message, 
                "❌ <b>Invalid Bot Token</b>\n"
                "Please send a valid Bot Token (e.g. <code>123456789:ABCdef...</code>) containing a colon.", 
                parse_mode="HTML", 
                reply_markup=get_cancel_markup()
            )
            return
            
        # Verify Bot Details with Telegram API dynamically
        import requests
        bot.reply_to(message, "⏳ <b>Verifying bot token with Telegram...</b>", parse_mode="HTML")
        try:
            res = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
            data = res.json()
            if not data.get("ok"):
                bot.reply_to(
                    message,
                    "❌ <b>Invalid Bot Token</b>\n"
                    "Telegram API rejected this token. Make sure it is correct and not revoked.",
                    parse_mode="HTML",
                    reply_markup=get_cancel_markup()
                )
                return
                
            bot_details = data["result"]
            bot_name = bot_details["first_name"]
            bot_username = bot_details["username"]
            bot_telegram_id = bot_details["id"]
            
            # Save token and details to Database
            db.execute_query(
                "INSERT INTO linked_bots (user_id, bot_token, bot_name, bot_username, bot_telegram_id) VALUES (%s, %s, %s, %s, %s)",
                (user_id, token, bot_name, bot_username, bot_telegram_id), commit=True
            )
            user_states[user_id] = None
            bot.reply_to(
                message, 
                f"✅ <b>Custom Bot added successfully!</b>\n\n"
                f"• Name: {bot_name}\n"
                f"• Username: @{bot_username}\n"
                f"• ID: <code>{bot_telegram_id}</code>", 
                parse_mode="HTML"
            )
            send_bots_settings_panel(message.chat.id, user_id)
        except Exception as e:
            logger.error(f"Error verifying/saving linked bot: {e}")
            bot.reply_to(message, f"❌ Failed to verify or save bot token: <code>{e}</code>", parse_mode="HTML")
            user_states[user_id] = None
            send_bots_settings_panel(message.chat.id, user_id)
            
    elif state == "WAITING_FOR_PHONE":
        phone = message.text.strip() if message.text else ""
        if not phone or not phone.startswith("+") or not phone[1:].replace(" ", "").isdigit():
            bot.reply_to(
                message,
                "❌ <b>Invalid Phone Number</b>\n"
                "Please enter a valid phone number with country code starting with <code>+</code> (e.g., <code>+1234567890</code>).",
                parse_mode="HTML",
                reply_markup=get_cancel_markup()
            )
            return
            
        phone = phone.replace(" ", "")
        
        # Check credentials and library availability for real Pyrogram connection
        API_ID = os.environ.get("API_ID") or config.get("api_id")
        API_HASH = os.environ.get("API_HASH") or config.get("api_hash")
        
        if PYROGRAM_AVAILABLE and API_ID and API_HASH:
            bot.reply_to(message, "⏳ <b>Connecting to Telegram... Please wait.</b>", parse_mode="HTML")
            try:
                # Initialize Pyrogram Client inside the background loop's context
                async def do_send_code():
                    c = Client(
                        name=f"temp_userbot_{user_id}",
                        api_id=int(API_ID),
                        api_hash=API_HASH,
                        in_memory=True
                    )
                    await c.connect()
                    sent_code = await c.send_code(phone)
                    return c, sent_code.phone_code_hash
                    
                client, phone_code_hash = run_async(do_send_code())
                
                temp_userbot_logins[user_id] = {
                    "client": client,
                    "phone": phone,
                    "phone_code_hash": phone_code_hash,
                    "simulation": False
                }
                user_states[user_id] = "WAITING_FOR_CODE"
                
                bot.send_message(
                    message.chat.id,
                    "📩 <b>Code Sent!</b>\n"
                    "I've sent a login code to your official Telegram app. Please paste it here:",
                    parse_mode="HTML",
                    reply_markup=get_cancel_markup()
                )
            except Exception as e:
                logger.error(f"Pyrogram code send error: {e}")
                bot.reply_to(
                    message,
                    f"❌ <b>Telegram Connection Error</b>\n"
                    f"Failed to request login code: <code>{e}</code>\n\n"
                    f"Please check your Telegram API ID/Hash configurations.",
                    parse_mode="HTML"
                )
                user_states[user_id] = None
                send_bots_settings_panel(message.chat.id)
        else:
            # Simulation Mode (if credentials/libraries are missing)
            warning_msg = ""
            if not PYROGRAM_AVAILABLE:
                warning_msg += "• <code>pyrogram</code> library is not installed.\n"
            if not (API_ID and API_HASH):
                warning_msg += "• <code>API_ID</code> / <code>API_HASH</code> environment variables are not set.\n"
                
            temp_userbot_logins[user_id] = {
                "phone": phone,
                "simulation": True
            }
            user_states[user_id] = "WAITING_FOR_CODE"
            
            bot.reply_to(
                message,
                f"⚠️ <b>Simulation Mode Activated</b>\n"
                f"The bot is running in layout testing mode because:\n{warning_msg}\n"
                f"💬 I've sent a login code to your official Telegram app. Please paste it here (enter any 5 digit code):",
                parse_mode="HTML",
                reply_markup=get_cancel_markup()
            )
            
    elif state == "WAITING_FOR_CODE":
        code = message.text.strip() if message.text else ""
        login_info = temp_userbot_logins.get(user_id)
        
        if not login_info:
            bot.reply_to(message, "❌ Session expired. Please click Add Userbot to start over.")
            user_states[user_id] = None
            return
            
        if login_info.get("simulation"):
            # Simulation mode success
            phone = login_info["phone"]
            sim_session = f"SIMULATED_SESSION_STRING_FOR_{phone}_{code}"
            
            try:
                sim_first_name = "Simulated User"
                sim_username = f"sim_user_{phone.replace('+', '')}"
                db.execute_query(
                    "INSERT INTO linked_userbots (user_id, phone, session_string, first_name, username) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, phone, sim_session, sim_first_name, sim_username), commit=True
                )
                temp_userbot_logins.pop(user_id, None)
                user_states[user_id] = None
                
                bot.reply_to(
                    message,
                    "✅ <b>Success! Your account is linked. We are now hosting your Userbot (Simulation Mode).</b>",
                    parse_mode="HTML"
                )
                send_bots_settings_panel(message.chat.id)
            except Exception as e:
                logger.error(f"Error saving simulated userbot: {e}")
                user_states[user_id] = None
                send_bots_settings_panel(message.chat.id)
        else:
            # Real pyrogram login
            bot.reply_to(message, "⏳ <b>Verifying code and signing in...</b>", parse_mode="HTML")
            client = login_info["client"]
            phone = login_info["phone"]
            phone_code_hash = login_info["phone_code_hash"]
            
            async def do_sign_in():
                try:
                    await client.sign_in(phone, phone_code_hash, code)
                    return "OK"
                except pyrogram.errors.SessionPasswordNeeded:
                    return "NEED_2FA"
                    
            try:
                res = run_async(do_sign_in())
                if res == "NEED_2FA":
                    user_states[user_id] = "WAITING_FOR_2FA"
                    bot.send_message(
                        message.chat.id,
                        "🔐 <b>2-Step Verification Active</b>\n"
                        "Your Telegram account requires a cloud password. Please enter your 2FA password below:",
                        parse_mode="HTML",
                        reply_markup=get_cancel_markup()
                    )
                else:
                    # Successfully authenticated
                    async def get_session_and_me():
                        session = await client.export_session_string()
                        me = await client.get_me()
                        return session, me.first_name, me.username
                    session_string, first_name, username = run_async(get_session_and_me())
                    
                    # Save to DB
                    db.execute_query(
                        "INSERT INTO linked_userbots (user_id, phone, session_string, first_name, username) VALUES (%s, %s, %s, %s, %s)",
                        (user_id, phone, session_string, first_name, username), commit=True
                    )
                    
                    # Disconnect temp client
                    try:
                        run_async(client.disconnect())
                    except:
                        pass
                        
                    temp_userbot_logins.pop(user_id, None)
                    user_states[user_id] = None
                    
                    bot.reply_to(
                        message,
                        "✅ <b>Success! Your account is linked. We are now hosting your Userbot.</b>",
                        parse_mode="HTML"
                    )
                    send_bots_settings_panel(message.chat.id)
            except Exception as e:
                logger.error(f"Pyrogram sign-in error: {e}")
                bot.reply_to(
                    message,
                    f"❌ <b>Sign-in Failed</b>\n"
                    f"Error: <code>{e}</code>\n\n"
                    f"Please click Add Userbot to start over.",
                    parse_mode="HTML"
                )
                try:
                    run_async(client.disconnect())
                except:
                    pass
                temp_userbot_logins.pop(user_id, None)
                user_states[user_id] = None
                send_bots_settings_panel(message.chat.id)
                
    elif state == "WAITING_FOR_2FA":
        password = message.text.strip() if message.text else ""
        login_info = temp_userbot_logins.get(user_id)
        
        if not login_info or login_info.get("simulation"):
            user_states[user_id] = None
            return
            
        client = login_info["client"]
        phone = login_info["phone"]
        
        bot.reply_to(message, "⏳ <b>Verifying cloud password...</b>", parse_mode="HTML")
        
        async def check_password_export_and_me():
            await client.check_password(password)
            session = await client.export_session_string()
            me = await client.get_me()
            return session, me.first_name, me.username
            
        try:
            session_string, first_name, username = run_async(check_password_export_and_me())
            # Save to DB
            db.execute_query(
                "INSERT INTO linked_userbots (user_id, phone, session_string, first_name, username) VALUES (%s, %s, %s, %s, %s)",
                (user_id, phone, session_string, first_name, username), commit=True
            )
            
            # Disconnect temp client
            try:
                run_async(client.disconnect())
            except:
                pass
                
            temp_userbot_logins.pop(user_id, None)
            user_states[user_id] = None
            
            bot.reply_to(
                message,
                "✅ <b>Success! Your account is linked. We are now hosting your Userbot.</b>",
                parse_mode="HTML"
            )
            send_bots_settings_panel(message.chat.id)
        except Exception as e:
            logger.error(f"Pyrogram check password error: {e}")
            bot.reply_to(
                message,
                f"❌ <b>Verification Failed</b>\n"
                f"Invalid cloud password: <code>{e}</code>\n\n"
                f"Please click Add Userbot to try again.",
                parse_mode="HTML"
            )
            try:
                run_async(client.disconnect())
            except:
                pass
            temp_userbot_logins.pop(user_id, None)
            user_states[user_id] = None
            send_bots_settings_panel(message.chat.id)
            
    elif state.startswith("WAITING_FOR_BTN_"):
        btn_key = state.replace("WAITING_FOR_BTN_", "")
        if not message.text:
            bot.reply_to(message, "❌ Please send text only for the button response message.", reply_markup=get_cancel_markup())
            return
            
        if "button_messages" not in config:
            config["button_messages"] = {}
        config["button_messages"][btn_key] = message.text
        save_config(config)
        user_states[user_id] = None
        
        bot.reply_to(message, "✅ <b>Button Response Message Updated Successfully!</b>", parse_mode="HTML")
        show_admin_buttons_menu(message.chat.id)
        
    elif state == "WAITING_FOR_TARGET_CHAT":
        # Check for cancel command or text
        if message.text and message.text.strip().lower() == "/cancel":
            user_states[user_id] = None
            bot.reply_to(message, "❌ <b>Operation Cancelled.</b>", parse_mode="HTML")
            send_channels_settings_panel(message.chat.id, user_id)
            return

        target_id = None
        target_title = None
        target_username = None
        
        if message.forward_from_chat:
            target_id = message.forward_from_chat.id
            target_title = message.forward_from_chat.title
            target_username = message.forward_from_chat.username
        elif message.text:
            text = message.text.strip()
            # Handle direct numeric ID (e.g. -100123456789)
            if (text.startswith("-") and text[1:].isdigit()) or text.isdigit():
                target_id = int(text)
                target_title = f"Chat {target_id}"
            elif text.startswith("@"):
                target_username = text[1:]
                target_title = text
                
        if target_id is not None or target_username is not None:
            try:
                db.execute_query(
                    "INSERT INTO target_chats (user_id, chat_id, chat_title, chat_username) VALUES (%s, %s, %s, %s)",
                    (user_id, target_id, target_title or f"@{target_username}", target_username), commit=True
                )
                user_states[user_id] = None
                bot.reply_to(
                    message,
                    f"✅ <b>Target Chat Added Successfully!</b>\n\n"
                    f"• Title: {target_title or f'@{target_username}'}\n"
                    f"• ID: <code>{target_id or 'Pending'}</code>",
                    parse_mode="HTML"
                )
                send_channels_settings_panel(message.chat.id, user_id)
            except Exception as e:
                logger.error(f"Error saving target chat to DB: {e}")
                bot.reply_to(message, f"❌ Failed to save target chat: <code>{e}</code>", parse_mode="HTML")
                user_states[user_id] = None
                send_channels_settings_panel(message.chat.id, user_id)
        else:
            bot.reply_to(
                message,
                "❌ <b>Invalid Input</b>\n"
                "Please forward a message from your target chat, or type `/cancel` to abort.",
                parse_mode="HTML"
            )
            
    elif state == "WAITING_FOR_CUSTOM_CAPTION":
        if message.text and message.text.strip().lower() == "/cancel":
            user_states[user_id] = None
            bot.reply_to(message, "❌ <b>Operation Cancelled.</b>", parse_mode="HTML")
            send_caption_settings_panel(message.chat.id, user_id)
            return
            
        if not message.text:
            bot.reply_to(message, "❌ Please send a text caption or type `/cancel` to abort.")
            return
            
        new_caption = message.text.strip()
        settings = get_user_settings(user_id)
        settings["custom_caption"] = new_caption
        save_user_settings(user_id, settings)
        
        user_states[user_id] = None
        bot.reply_to(message, "✅ <b>Custom Caption updated successfully!</b>", parse_mode="HTML")
        send_caption_settings_panel(message.chat.id, user_id)
        
    elif state == "WAITING_FOR_REMOVE_WORD":
        if message.text and message.text.strip().lower() == "/cancel":
            user_states[user_id] = None
            bot.reply_to(message, "❌ <b>Operation Cancelled.</b>", parse_mode="HTML")
            send_remove_words_settings_panel(message.chat.id, user_id)
            return
            
        if not message.text:
            bot.reply_to(message, "❌ Please send the word(s) to remove or type `/cancel` to abort.")
            return
            
        input_text = message.text.strip()
        new_words = [w.strip() for w in input_text.split(",") if w.strip()]
        
        settings = get_user_settings(user_id)
        existing_words = settings.get("remove_words", [])
        
        added_count = 0
        for w in new_words:
            if w not in existing_words:
                existing_words.append(w)
                added_count += 1
                
        settings["remove_words"] = existing_words
        save_user_settings(user_id, settings)
        
        user_states[user_id] = None
        bot.reply_to(message, f"✅ <b>Added {added_count} word(s) to remove list!</b>", parse_mode="HTML")
        send_remove_words_settings_panel(message.chat.id, user_id)
        
    elif state == "WAITING_FOR_DELETE_REMOVE_WORD":
        if message.text and message.text.strip().lower() == "/cancel":
            user_states[user_id] = None
            bot.reply_to(message, "❌ <b>Operation Cancelled.</b>", parse_mode="HTML")
            send_remove_words_settings_panel(message.chat.id, user_id)
            return
            
        if not message.text:
            bot.reply_to(message, "❌ Please send the word to delete or type `/cancel` to abort.")
            return
            
        word_to_delete = message.text.strip()
        settings = get_user_settings(user_id)
        existing_words = settings.get("remove_words", [])
        
        if word_to_delete in existing_words:
            existing_words.remove(word_to_delete)
            settings["remove_words"] = existing_words
            save_user_settings(user_id, settings)
            bot.reply_to(message, f"✅ <b>Word '<code>{word_to_delete}</code>' deleted from remove list!</b>", parse_mode="HTML")
        else:
            bot.reply_to(message, f"❌ <b>Word '<code>{word_to_delete}</code>' not found in your list.</b>", parse_mode="HTML")
            
        user_states[user_id] = None
        send_remove_words_settings_panel(message.chat.id, user_id)
        
    elif state == "WAITING_FOR_SOURCE_CHAT":
        if message.text and message.text.strip().lower() == "/cancel":
            user_states[user_id] = None
            bot.reply_to(message, "❌ <b>Operation Cancelled.</b>", parse_mode="HTML")
            return
            
        source_id = None
        source_title = None
        
        if message.forward_from_chat:
            source_id = message.forward_from_chat.id
            source_title = message.forward_from_chat.title or message.forward_from_chat.username or "Source Chat"
        elif message.text:
            text = message.text.strip()
            parsed_id, parsed_title = parse_telegram_link(text)
            if parsed_id is not None:
                source_id = parsed_id
                source_title = parsed_title
            else:
                if (text.startswith("-") and text[1:].isdigit()) or text.isdigit():
                    source_id = int(text)
                    source_title = f"Chat {source_id}"
                elif text.startswith("@"):
                    source_id = text
                    source_title = text
                    
        if source_id is not None:
            # Dynamically verify if custom bot or userbot can access this chat
            bot.reply_to(message, "⏳ <b>Verifying access to the source chat...</b>", parse_mode="HTML")
            has_access, err_msg, resolved_title = check_client_source_access(user_id, source_id)
            if not has_access:
                bot.reply_to(
                    message,
                    f"⚠️ <b>Access Check Failed</b>\n\n{err_msg}\n\n"
                    f"Please verify that the bot/userbot has been added to the chat and try again, or type `/cancel`.",
                    parse_mode="HTML"
                )
                return
                
            if resolved_title:
                source_title = resolved_title
                
            user_states[user_id] = None
            targets = db.execute_query("SELECT chat_id, chat_title FROM target_chats WHERE user_id = %s ORDER BY id DESC", (user_id,), fetch="all")
            bots = db.execute_query("SELECT bot_name, bot_username FROM linked_bots WHERE user_id = %s ORDER BY id DESC", (user_id,), fetch="all")
            userbots = db.execute_query("SELECT username, phone FROM linked_userbots WHERE user_id = %s ORDER BY id DESC", (user_id,), fetch="all")
            
            if not targets:
                bot.reply_to(message, "❌ No target chats configured. Please configure a target chat first.", parse_mode="HTML")
                return
                
            target_chat_id, target_title = targets[0]
            
            bot_display = "Bot"
            if bots:
                bot_display = bots[0][0] or f"@{bots[0][1]}"
            elif userbots:
                bot_display = userbots[0][0] or userbots[0][1]
                
            temp_forward_confirms[user_id] = {
                "source_id": source_id,
                "source_title": source_title,
                "target_chat_id": target_chat_id,
                "target_title": target_title,
                "bot_display": bot_display
            }
            
            check_text = (
                "⚠️ <b>DOUBLE CHECK</b>\n\n"
                "<blockquote>"
                "PLEASE VERIFY THE FOLLOWING DETAILS:\n\n"
                f"🤖 <b>BOT:</b> {bot_display}\n"
                f"📤 <b>FROM:</b> {source_title}\n"
                f"📥 <b>TO:</b> {target_title}\n"
                "⏭️ <b>SKIP:</b> 0\n\n"
                "📌 <b>IMPORTANT:</b>\n"
                f"• {bot_display} MUST BE ADMIN IN TARGET CHAT\n"
                "• FOR PRIVATE SOURCE, BOT NEEDS ADMIN\n"
                "OR USERBOT MUST BE MEMBER"
                "</blockquote>\n\n"
                "✅ <i>CLICK YES IF EVERYTHING IS CORRECT</i>"
            )
            
            markup = InlineKeyboardMarkup()
            markup.row(
                InlineKeyboardButton("Yes", callback_data="confirm_forward_yes"),
                InlineKeyboardButton("No", callback_data="confirm_forward_no")
            )
            
            bot.send_message(message.chat.id, check_text, reply_markup=markup, parse_mode="HTML")
        else:
            bot.reply_to(
                message,
                "❌ <b>Invalid Source Chat</b>\n"
                "Please forward a message from the source chat, send a message link, or type `/cancel` to abort.",
                parse_mode="HTML"
            )

# --- CALLBACK QUERY HANDLERS ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    """Processes inline keyboard button clicks."""
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    data = call.data
    
    # ─── USER BUTTON CALLBACKS ───
    if data.startswith("user_"):
        bot.answer_callback_query(call.id)
        
        if data == "user_settings":
            show_settings_panel(call)
            return
            
        button_messages = config.get("button_messages", DEFAULT_CONFIG["button_messages"])
        response_text = button_messages.get(data)
        
        if not response_text:
            # Fallback to default messages
            response_text = DEFAULT_CONFIG["button_messages"].get(data, "Response not configured.")
            
        try:
            bot.send_message(chat_id, response_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error sending callback reply: {e}")
            
    # ─── SETTINGS PANEL CALLBACKS ───
    elif data.startswith("settings_"):
        if data == "settings_back":
            bot.answer_callback_query(call.id)
            show_welcome_panel(call)
        elif data == "settings_bots":
            bot.answer_callback_query(call.id)
            show_bots_settings_panel(call)
        elif data == "settings_bots_add":
            bot.answer_callback_query(call.id)
            user_states[user_id] = "WAITING_FOR_BOT_TOKEN"
            bot.send_message(
                chat_id,
                "🤖 <b>Adding Custom Bot</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                "Please send the Bot Token (from @BotFather) of the bot you want to add.\n\n"
                "<i>This bot will be used to forward content from target groups to source groups.</i>",
                reply_markup=get_cancel_markup(),
                parse_mode="HTML"
            )
        elif data == "settings_bots_userbot":
            bot.answer_callback_query(call.id)
            user_states[user_id] = "WAITING_FOR_PHONE"
            bot.send_message(
                chat_id,
                "👤 <b>Adding Custom Userbot</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                "Please enter your Phone Number (with country code, e.g., <code>+1234567890</code>):",
                reply_markup=get_cancel_markup(),
                parse_mode="HTML"
            )
        elif data == "settings_menu":
            bot.answer_callback_query(call.id)
            show_settings_panel(call)
        elif data == "settings_channels":
            bot.answer_callback_query(call.id)
            show_channels_settings_panel(call)
        elif data == "settings_channels_add":
            bot.answer_callback_query(call.id)
            user_states[user_id] = "WAITING_FOR_TARGET_CHAT"
            bot.send_message(
                chat_id,
                "<b>( SET TARGET CHAT )</b>\n\n"
                "Forward a message from Your target chat\n"
                "/cancel - cancel this process",
                parse_mode="HTML"
            )
        elif data == "settings_caption":
            bot.answer_callback_query(call.id)
            show_caption_settings_panel(call)
        elif data == "settings_caption_add":
            bot.answer_callback_query(call.id)
            user_states[user_id] = "WAITING_FOR_CUSTOM_CAPTION"
            bot.send_message(
                chat_id,
                "🖊️ <b>Add/Edit Custom Caption</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Please send the new custom caption.\n\n"
                "You can use:\n"
                "- <code>{filename}</code> : Filename\n"
                "- <code>{size}</code> : File size\n"
                "- <code>{caption}</code> : Default caption\n\n"
                "Type /cancel to abort.",
                reply_markup=get_cancel_markup(),
                parse_mode="HTML"
            )
        elif data == "settings_caption_remove":
            bot.answer_callback_query(call.id, "✅ Custom caption removed!", show_alert=True)
            settings = get_user_settings(user_id)
            settings["custom_caption"] = None
            save_user_settings(user_id, settings)
            show_caption_settings_panel(call)
        elif data == "settings_filters":
            bot.answer_callback_query(call.id)
            show_filters_settings_panel(call, 1)
        elif data == "settings_filters_page_1":
            bot.answer_callback_query(call.id)
            show_filters_settings_panel(call, 1)
        elif data == "settings_filters_page_2":
            bot.answer_callback_query(call.id)
            show_filters_settings_panel(call, 2)
        elif data == "settings_remove_words":
            bot.answer_callback_query(call.id)
            show_remove_words_settings_panel(call)
        else:
            option_name = data.replace("settings_", "").replace("_", " ").title()
            bot.answer_callback_query(
                call.id,
                f"⚙️ {option_name} settings will be configured here.",
                show_alert=True
            )
            
    # ─── BOTS MANAGEMENT CALLBACKS ───
    elif data.startswith("manage_bot_"):
        bot.answer_callback_query(call.id)
        bot_id = int(data.replace("manage_bot_", ""))
        show_bot_details_panel(call, bot_id)
        
    elif data.startswith("manage_userbot_"):
        bot.answer_callback_query(call.id)
        u_id = int(data.replace("manage_userbot_", ""))
        show_userbot_details_panel(call, u_id)
        
    elif data.startswith("remove_bot_"):
        bot_id = int(data.replace("remove_bot_", ""))
        try:
            db.execute_query("DELETE FROM linked_bots WHERE id = %s", (bot_id,), commit=True)
            bot.answer_callback_query(call.id, "✅ Bot removed successfully!", show_alert=True)
        except Exception as e:
            logger.error(f"Error removing bot from DB: {e}")
            bot.answer_callback_query(call.id, "❌ Error removing bot.", show_alert=True)
        show_bots_settings_panel(call)
        
    elif data.startswith("remove_userbot_"):
        u_id = int(data.replace("remove_userbot_", ""))
        try:
            db.execute_query("DELETE FROM linked_userbots WHERE id = %s", (u_id,), commit=True)
            bot.answer_callback_query(call.id, "✅ Userbot removed successfully!", show_alert=True)
        except Exception as e:
            logger.error(f"Error removing userbot from DB: {e}")
            bot.answer_callback_query(call.id, "❌ Error removing userbot.", show_alert=True)
        show_bots_settings_panel(call)
            
    # ─── CHANNELS MANAGEMENT CALLBACKS ───
    elif data.startswith("manage_channel_"):
        bot.answer_callback_query(call.id)
        c_id = int(data.replace("manage_channel_", ""))
        show_channel_details_panel(call, c_id)
        
    elif data.startswith("remove_channel_"):
        c_id = int(data.replace("remove_channel_", ""))
        try:
            db.execute_query("DELETE FROM target_chats WHERE id = %s", (c_id,), commit=True)
            bot.answer_callback_query(call.id, "✅ Channel removed successfully!", show_alert=True)
        except Exception as e:
            logger.error(f"Error removing channel from DB: {e}")
            bot.answer_callback_query(call.id, "❌ Error removing channel.", show_alert=True)
        show_channels_settings_panel(call)
            
    # ─── REMOVE WORDS CALLBACKS ───
    elif data.startswith("remove_words_"):
        bot.answer_callback_query(call.id)
        action = data.replace("remove_words_", "")
        
        if action == "add":
            user_states[user_id] = "WAITING_FOR_REMOVE_WORD"
            bot.send_message(
                chat_id,
                "🚫 <b>Add Remove Word(s)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Please send the word (or comma-separated list of words) you want to remove from post captions.\n\n"
                "Type /cancel to abort.",
                reply_markup=get_cancel_markup(),
                parse_mode="HTML"
            )
        elif action == "delete":
            user_states[user_id] = "WAITING_FOR_DELETE_REMOVE_WORD"
            bot.send_message(
                chat_id,
                "🚫 <b>Delete Remove Word</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Please send the exact word you want to delete from your remove list.\n\n"
                "Type /cancel to abort.",
                reply_markup=get_cancel_markup(),
                parse_mode="HTML"
            )
        elif action == "view":
            settings = get_user_settings(user_id)
            words = settings.get("remove_words", [])
            if not words:
                bot.send_message(chat_id, "ℹ️ <b>Your remove words list is empty.</b>", parse_mode="HTML")
            else:
                words_list = "\n".join([f"• <code>{w}</code>" for w in words])
                bot.send_message(
                    chat_id,
                    "📋 <b>Your Remove Words List:</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"{words_list}",
                    parse_mode="HTML"
                )
        elif action == "clear":
            settings = get_user_settings(user_id)
            settings["remove_words"] = []
            save_user_settings(user_id, settings)
            bot.send_message(chat_id, "🗑️ <b>All remove words cleared!</b>", parse_mode="HTML")
            show_remove_words_settings_panel(call)
            
    # ─── TOGGLE FILTER CALLBACKS ───
    elif data.startswith("toggle_filter_"):
        bot.answer_callback_query(call.id)
        parts = data.replace("toggle_filter_", "").split("_")
        page = int(parts[-1])
        key = "_".join(parts[:-1])
        
        settings = get_user_settings(user_id)
        filters = settings.get("filters", {})
        filters[key] = not filters.get(key, False)
        settings["filters"] = filters
        save_user_settings(user_id, settings)
        
        show_filters_settings_panel(call, page)
        
    # ─── FORWARDING CALLBACKS ───
    elif data == "confirm_forward_yes":
        confirm_data = temp_forward_confirms.pop(user_id, None)
        if not confirm_data:
            bot.answer_callback_query(call.id, "❌ No pending forwarding confirmation found.", show_alert=True)
            return
            
        bot.answer_callback_query(call.id, "✅ Starting forwarding...")
        
        # Send initial Forward Status message
        initial_text = (
            "✨ <b>FORWARD STATUS</b>\n\n"
            "<blockquote>"
            "📥 <b>FETCHED:</b> 0\n"
            "📤 <b>FORWARDED:</b> 0\n"
            "🔄 <b>DUPLICATES:</b> 0\n"
            "🗑️ <b>DELETED:</b> 0\n"
            "⏭️ <b>SKIPPED:</b> 0\n"
            "🎯 <b>FILTERED:</b> 0\n"
            "⚡ <b>STATUS:</b> Forwarding\n"
            "📊 <b>PROGRESS:</b> 0%\n\n"
            "✨ ⏳ Processing"
            "</blockquote>"
         )
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("◇" * 20, callback_data="progress_bar_click"))
        markup.add(InlineKeyboardButton("❌ Cancel", callback_data="cancel_forward_task"))
        
        try:
            status_msg = bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=initial_text,
                reply_markup=markup,
                parse_mode="HTML"
            )
        except Exception:
            status_msg = bot.send_message(chat_id, initial_text, reply_markup=markup, parse_mode="HTML")
            
        # Launch background forwarding task
        asyncio.run_coroutine_threadsafe(
            run_forwarding_task(
                user_id=user_id,
                source_id=confirm_data["source_id"],
                target_chat_id=confirm_data["target_chat_id"],
                status_message_id=status_msg.message_id,
                chat_id=chat_id
            ),
            background_loop
        )
        
    elif data == "confirm_forward_no":
        temp_forward_confirms.pop(user_id, None)
        bot.answer_callback_query(call.id, "❌ Forwarding cancelled.")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
            
    elif data == "cancel_forward_task":
        if user_id in active_forwarding_tasks:
            active_forwarding_tasks[user_id]["cancelled"] = True
            bot.answer_callback_query(call.id, "🛑 Cancelling forwarding task...", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ No active forwarding task found.", show_alert=True)
            
    elif data == "progress_bar_click":
        bot.answer_callback_query(call.id)
            
    # ─── ADMIN BUTTON CALLBACKS ───
    elif data.startswith("admin_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Access Denied: You are not an Admin.", show_alert=True)
            return
            
        bot.answer_callback_query(call.id)
        
        if data == "admin_menu":
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except:
                pass
            # Create a mock message to reuse the command function
            mock_msg = telebot.types.Message(
                message_id=call.message.message_id,
                from_user=call.from_user,
                date=call.message.date,
                chat=call.message.chat,
                content_type="text",
                options={},
                json_string=""
            )
            cmd_admin(mock_msg)
            
        elif data == "admin_intro_menu":
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except:
                pass
            show_admin_intro_menu(chat_id)
            
        elif data == "admin_buttons_menu":
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except:
                pass
            show_admin_buttons_menu(chat_id)
            
        elif data == "admin_edit_text":
            user_states[user_id] = "WAITING_FOR_TEXT"
            bot.send_message(
                chat_id,
                "📝 <b>Edit Welcome Message Text</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                "Please send the new text format.\n\n"
                "<b>Variables you can include:</b>\n"
                "• <code>{name}</code> - Displays the user's first name.\n"
                "• <code>{username}</code> - Displays user's @username.\n"
                "• <code>{id}</code> - Displays the user's ID.\n\n"
                "<i>HTML tags like &lt;b&gt;, &lt;i&gt;, and &lt;code&gt; are supported.</i>",
                reply_markup=get_cancel_markup(),
                parse_mode="HTML"
            )
            
        elif data == "admin_edit_photo":
            user_states[user_id] = "WAITING_FOR_PHOTO"
            bot.send_message(
                chat_id,
                "🖼️ <b>Edit Welcome Message Photo</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                "Please upload a new image or paste a direct image URL (starting with <code>http://</code> or <code>https://</code>).",
                reply_markup=get_cancel_markup(),
                parse_mode="HTML"
            )
            
        elif data.startswith("admin_edit_btn_"):
            btn_key = data.replace("admin_edit_btn_", "")
            user_states[user_id] = f"WAITING_FOR_BTN_{btn_key}"
            
            btn_display = btn_key.replace("user_", "").replace("_", " ").title()
            bot.send_message(
                chat_id,
                f"📝 <b>Edit {btn_display} Button Message</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                f"Please send the new response message for the <b>{btn_display}</b> button.\n\n"
                f"<i>All HTML formatting tags (like &lt;b&gt;, &lt;i&gt;, &lt;code&gt;, &lt;blockquote&gt;) are supported.</i>",
                reply_markup=get_cancel_markup(),
                parse_mode="HTML"
            )
            
        elif data == "admin_preview":
            bot.send_message(chat_id, "👁️ <b>WELCOME PREVIEW:</b>\n━━━━━━━━━━━━━━━━━━━━", parse_mode="HTML")
            send_welcome_message(chat_id, call.from_user)
            # Resend admin panel link for ease of navigation
            bot.send_message(
                chat_id, 
                "👑 <b>Admin Options:</b>", 
                reply_markup=InlineKeyboardMarkup().row(InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_menu"))
            )
            
        elif data == "admin_user_view":
            # Send standard user welcome view
            send_welcome_message(chat_id, call.from_user)
            
        elif data == "admin_cancel":
            current_state = user_states.get(user_id)
            user_states[user_id] = None
            
            # Clean up Pyrogram active login if exists
            if user_id in temp_userbot_logins:
                info = temp_userbot_logins.pop(user_id, None)
                if info and "client" in info:
                    try:
                        run_async(info["client"].disconnect())
                    except:
                        pass
                        
            bot.send_message(chat_id, "❌ <b>Operation Cancelled.</b>", parse_mode="HTML")
            
            if current_state:
                if current_state.startswith("WAITING_FOR_BTN_"):
                    show_admin_buttons_menu(chat_id)
                elif current_state in ["WAITING_FOR_BOT_TOKEN", "WAITING_FOR_PHONE", "WAITING_FOR_CODE", "WAITING_FOR_2FA"]:
                    send_bots_settings_panel(chat_id)
                elif current_state == "WAITING_FOR_TARGET_CHAT":
                    send_channels_settings_panel(chat_id)
                elif current_state == "WAITING_FOR_CUSTOM_CAPTION":
                    send_caption_settings_panel(chat_id)
                elif current_state in ["WAITING_FOR_REMOVE_WORD", "WAITING_FOR_DELETE_REMOVE_WORD"]:
                    send_remove_words_settings_panel(chat_id)
                else:
                    show_admin_intro_menu(chat_id)
            else:
                show_admin_intro_menu(chat_id)

# --- STARTUP RUN ---
if __name__ == "__main__":
    logger.info("🚀 Starting Bot Polling...")
    
    if TOKEN == "INVALID_TOKEN_PLACEHOLDER":
        logger.critical("❌ ERROR: Bot Token is missing! Edit config.json with your Telegram Bot Token.")
        print("\n" + "="*60)
        print("CRITICAL NOTICE: Please configure the bot token!")
        print(f"Open this file and add your token: {CONFIG_FILE}")
        print("="*60 + "\n")
        # Do not exit so that the user doesn't get a crashed process immediately, 
        # allowing them to see this prompt in logs.
    else:
        logger.info("Bot successfully initialized.")
        logger.info("Commands available: /start, /admin, /myid, /forward")
        
    try:
        # Start the bot in non-stop polling mode
        bot.infinity_polling(skip_pending=True)
    except Exception as e:
        logger.critical(f"Bot polling crashed: {e}")
