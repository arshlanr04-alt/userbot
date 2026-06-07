import html
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from pyrogram.errors import RPCError
import database as db

logger = logging.getLogger(__name__)

def format_start_text(text: str, message: Message) -> str:
    """Formats the start text template with escaped user details."""
    if not text:
        return ""
        
    user = message.from_user
    if not user:
        return text
        
    # Escape user parameters for HTML safety
    first_name = html.escape(user.first_name or "")
    last_name = html.escape(user.last_name or "")
    username = html.escape(user.username or "")
    user_id = str(user.id)
    mention = f'<a href="tg://user?id={user_id}">{first_name}</a>'
    
    # Perform substitutions safely
    formatted = text.replace("{first_name}", first_name)
    formatted = formatted.replace("{last_name}", last_name)
    formatted = formatted.replace("{username}", username)
    formatted = formatted.replace("{id}", user_id)
    formatted = formatted.replace("{mention}", mention)
    
    return formatted

def build_inline_keyboard(buttons_data):
    """Builds Pyrogram InlineKeyboardMarkup from database records."""
    rows = {}
    for btn in buttons_data:
        row_idx = btn.get("row", 0)
        if row_idx not in rows:
            rows[row_idx] = []
            
        btn_label = btn["label"]
        btn_type = btn["type"]
        btn_val = btn["value"]
        
        if btn_type == "url":
            rows[row_idx].append(InlineKeyboardButton(text=btn_label, url=btn_val))
        else:
            rows[row_idx].append(InlineKeyboardButton(text=btn_label, callback_data=btn_val))
            
    keyboard = []
    for r in sorted(rows.keys()):
        keyboard.append(rows[r])
        
    return InlineKeyboardMarkup(keyboard) if keyboard else None

async def generate_start_message(message: Message):
    """Generates the formatted message text and keyboard markup for start."""
    settings = await db.get_settings()
    if not settings:
        # Fallback if DB not loaded properly
        return "Welcome to the bot!", None, None
        
    header_raw = settings.get("header_text", "")
    body_raw = settings.get("body_text", "")
    is_quote = settings.get("is_quote", 1)
    photo = settings.get("photo_url_or_file_id")
    
    # Format texts
    header_formatted = format_start_text(header_raw, message)
    body_formatted = format_start_text(body_raw, message)
    
    # Combine texts
    text_content = ""
    if header_formatted:
        text_content += header_formatted
        
    if body_formatted:
        if text_content:
            text_content += "\n\n"
            
        if is_quote:
            text_content += f"<blockquote>{body_formatted}</blockquote>"
        else:
            text_content += body_formatted
            
    # Fetch buttons
    buttons_data = await db.get_buttons()
    reply_markup = build_inline_keyboard(buttons_data)
    
    return text_content, photo, reply_markup

@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    """Responds to the /start command."""
    text_content, photo, reply_markup = await generate_start_message(message)
    
    if photo:
        try:
            # Try to send as photo
            await client.send_photo(
                chat_id=message.chat.id,
                photo=photo,
                caption=text_content,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            return
        except RPCError as e:
            logger.error(f"Failed to send photo start message (likely invalid URL/file_id): {e}")
            # Fallback to sending text message
            
    # Send as normal text message (fallback or if no photo configured)
    try:
        await client.send_message(
            chat_id=message.chat.id,
            text=text_content,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    except RPCError as e:
        logger.error(f"Failed to send start message: {e}")

@Client.on_callback_query(filters.regex("^(about_cb|settings_cb|status_cb)$"))
async def default_callbacks(client: Client, callback_query: CallbackQuery):
    """Responds to the default callback buttons on start message."""
    data = callback_query.data
    if data == "about_cb":
        await callback_query.answer(
            "ℹ️ About This Bot\n\nThis is a customizable startup bot with a premium administration control panel.",
            show_alert=True
        )
    elif data == "settings_cb":
        await callback_query.answer(
            "⚙️ Settings\n\nUser settings configurations will appear here in future updates.",
            show_alert=True
        )
    elif data == "status_cb":
        await callback_query.answer(
            "📊 Status\n\nSystem Status: Online\nAll services running normally.",
            show_alert=True
        )
