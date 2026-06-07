import os
import json
import logging
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

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
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "bot_token": "YOUR_BOT_TOKEN_HERE",
    "admin_ids": [],
    "welcome_text": (
        "✨ HI {name} WELCOME TO OUR BOT 👋\n\n"
        "🎯 <b>I'M AN ADVANCED FORWARD BOT\nWITH SPECIAL FEATURES</b>\n\n"
        "⚡ <i>CLICK THE BUTTONS BELOW TO\nEXPLORE MORE</i>"
    ),
    "welcome_photo": "https://picsum.photos/800/500"  # High quality random placeholder
}

# --- CONFIG MANAGEMENT ---
def load_config():
    """Loads configuration from JSON file, creating it if it doesn't exist."""
    if not os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
            logger.info(f"Created default configuration file at {CONFIG_FILE}")
            return DEFAULT_CONFIG
        except Exception as e:
            logger.error(f"Error creating config file: {e}")
            return DEFAULT_CONFIG
    
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
            # Ensure all keys exist
            updated = False
            for k, v in DEFAULT_CONFIG.items():
                if k not in config:
                    config[k] = v
                    updated = True
            if updated:
                save_config(config)
            return config
    except Exception as e:
        logger.error(f"Error reading config file: {e}. Using defaults.")
        return DEFAULT_CONFIG

def save_config(config):
    """Saves configuration back to JSON file."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        logger.info("Configuration saved successfully.")
        return True
    except Exception as e:
        logger.error(f"Error saving config file: {e}")
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
    """Returns the admin control panel inline keyboard."""
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📝 Edit Text", callback_data="admin_edit_text"),
        InlineKeyboardButton("🖼️ Edit Photo", callback_data="admin_edit_photo")
    )
    markup.row(
        InlineKeyboardButton("👁️ Preview Welcome", callback_data="admin_preview"),
        InlineKeyboardButton("🏠 Open User View", callback_data="admin_user_view")
    )
    return markup

def get_cancel_markup():
    """Returns a cancel button for admin operations."""
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel"))
    return markup

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
    
    # Show Admin Control Panel
    welcome_photo = config.get("welcome_photo", "None")
    welcome_text = config.get("welcome_text", "")
    
    admin_msg = (
        "👑 <b>ADMIN CONTROL PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Manage how your bot is displayed to users.\n\n"
        f"🖼️ <b>Current Photo:</b>\n"
        f"<code>{welcome_photo[:60] + '...' if len(str(welcome_photo)) > 60 else welcome_photo}</code>\n\n"
        f"📝 <b>Current Text:</b>\n"
        f"<blockquote>{welcome_text}</blockquote>\n\n"
        "💡 Use the buttons below to modify settings:"
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
@bot.message_handler(func=lambda msg: msg.from_user.id in user_states and user_states[msg.from_user.id] is not None)
def handle_admin_inputs(message):
    """Processes incoming text and media from admins based on active editing states."""
    user_id = message.from_user.id
    state = user_states.get(user_id)
    
    if not is_admin(user_id):
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
        # Redisplay admin panel
        cmd_admin(message)
        
    elif state == "WAITING_FOR_PHOTO":
        # Check if the user sent a photo
        if message.photo:
            # Take the highest resolution photo file ID
            photo_id = message.photo[-1].file_id
            config["welcome_photo"] = photo_id
            save_config(config)
            user_states[user_id] = None
            
            bot.reply_to(message, "✅ <b>Welcome Photo Updated (using Telegram File ID)!</b>", parse_mode="HTML")
            cmd_admin(message)
            
        # Check if they sent a text (assumed to be a URL)
        elif message.text:
            input_text = message.text.strip()
            # Basic validation
            if input_text.startswith("http://") or input_text.startswith("https://"):
                config["welcome_photo"] = input_text
                save_config(config)
                user_states[user_id] = None
                
                bot.reply_to(message, "✅ <b>Welcome Photo Updated (using URL)!</b>", parse_mode="HTML")
                cmd_admin(message)
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

# --- CALLBACK QUERY HANDLERS ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    """Processes inline keyboard button clicks."""
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    data = call.data
    
    # ─── USER BUTTON CALLBACKS ───
    if data.startswith("user_"):
        # Answer to clear the loading spinner on Telegram client
        bot.answer_callback_query(call.id)
        
        button_name = data.replace("user_", "").replace("_", " ").title()
        
        # Friendly response messages for the core user buttons
        response_texts = {
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
        
        response_text = response_texts.get(data, f"You clicked on: <b>{button_name}</b>")
        
        # Send reply message to user (without erasing the welcome page)
        try:
            bot.send_message(chat_id, response_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error sending callback reply: {e}")
            
    # ─── ADMIN BUTTON CALLBACKS ───
    elif data.startswith("admin_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Access Denied: You are not an Admin.", show_alert=True)
            return
            
        bot.answer_callback_query(call.id)
        
        if data == "admin_menu":
            # Delete shortcut button message and show panel
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except:
                pass
            # Trigger admin panel
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
            user_states[user_id] = None
            bot.send_message(chat_id, "❌ <b>Operation Cancelled.</b>", parse_mode="HTML")
            # Re-display panel
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
