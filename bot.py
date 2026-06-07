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
                    "active BOOLEAN DEFAULT TRUE, "
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
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
            
        logger.info("Database initialized successfully.")

# Initialize DB Manager
db = DBManager()

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
        "SELECT id, phone FROM linked_userbots WHERE user_id = %s",
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
        for u_id, phone in linked_userbots:
            markup.add(InlineKeyboardButton(f"👤 Userbot ({phone})", callback_data=f"manage_userbot_{u_id}"))
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

# --- STATE-BASED MESSAGE HANDLER ---
@bot.message_handler(content_types=['text', 'photo'], func=lambda msg: msg.from_user.id in user_states and user_states[msg.from_user.id] is not None)
def handle_admin_inputs(message):
    """Processes incoming text and media from admins based on active editing states."""
    user_id = message.from_user.id
    state = user_states.get(user_id)
    
    # Allow users to complete the custom bot/userbot wizards, but restrict introductory configs to admins
    if not is_admin(user_id) and state not in ["WAITING_FOR_BOT_TOKEN", "WAITING_FOR_PHONE", "WAITING_FOR_CODE", "WAITING_FOR_2FA"]:
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
                db.execute_query(
                    "INSERT INTO linked_userbots (user_id, phone, session_string) VALUES (%s, %s, %s)",
                    (user_id, phone, sim_session), commit=True
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
                    async def get_session():
                        return await client.export_session_string()
                    session_string = run_async(get_session())
                    
                    # Save to DB
                    db.execute_query(
                        "INSERT INTO linked_userbots (user_id, phone, session_string) VALUES (%s, %s, %s)",
                        (user_id, phone, session_string), commit=True
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
        
        async def check_password_and_export():
            await client.check_password(password)
            return await client.export_session_string()
            
        try:
            session_string = run_async(check_password_and_export())
            # Save to DB
            db.execute_query(
                "INSERT INTO linked_userbots (user_id, phone, session_string) VALUES (%s, %s, %s)",
                (user_id, phone, session_string), commit=True
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
        logger.info("Commands available: /start, /admin, /myid")
        
    try:
        # Start the bot in non-stop polling mode
        bot.infinity_polling(skip_pending=True)
    except Exception as e:
        logger.critical(f"Bot polling crashed: {e}")
