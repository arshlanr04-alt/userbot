import html
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from pyrogram.errors import RPCError
import config
import database as db

logger = logging.getLogger(__name__)

def format_start_text(text: str, user) -> str:
    """Formats the start text template with escaped user details."""
    if not text or not user:
        return text or ""
        
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

async def generate_start_message(user, is_admin: bool = False):
    """Generates the formatted message text and keyboard markup for start."""
    settings = await db.get_settings()
    if not settings:
        return "Welcome to the bot!", None, None
        
    header_raw = settings.get("header_text", "")
    body_raw = settings.get("body_text", "")
    is_quote = settings.get("is_quote", 1)
    photo = settings.get("photo_url_or_file_id")
    
    # Format texts
    header_formatted = format_start_text(header_raw, user)
    body_formatted = format_start_text(body_raw, user)
    
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
    
    # Group buttons by row
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
        
    # Append Admin Panel button if user is admin
    if is_admin:
        keyboard.append([InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_main")])
        
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    return text_content, photo, reply_markup

@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    """Responds to the /start command."""
    user = message.from_user
    user_id = user.id if user else 0
    is_admin = user_id in config.ADMIN_IDS
    
    text_content, photo, reply_markup = await generate_start_message(user, is_admin=is_admin)
    
    if photo:
        try:
            # Try to send as photo with HTML parsing
            await client.send_photo(
                chat_id=message.chat.id,
                photo=photo,
                caption=text_content,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            return
        except RPCError as e:
            logger.warning(f"Failed to send photo start message with HTML (retrying as plain text): {e}")
            try:
                # Try sending photo with plain text fallback (e.g. if HTML was broken)
                await client.send_photo(
                    chat_id=message.chat.id,
                    photo=photo,
                    caption=text_content,
                    parse_mode=None,
                    reply_markup=reply_markup
                )
                return
            except RPCError as photo_err:
                logger.error(f"Failed to send photo start message even with plain text: {photo_err}")
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
        logger.warning(f"Failed to send start message with HTML (retrying as plain text): {e}")
        try:
            await client.send_message(
                chat_id=message.chat.id,
                text=text_content,
                parse_mode=None,
                reply_markup=reply_markup
            )
        except RPCError as text_err:
            logger.error(f"Failed to send start message even with plain text fallback: {text_err}")

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
