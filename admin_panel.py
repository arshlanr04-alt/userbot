import logging
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from pyrogram.errors import RPCError
import config
import database as db
from start_handler import generate_start_message

logger = logging.getLogger(__name__)

# Admin commands filters
def is_admin(_, __, message: Message) -> bool:
    return message.from_user and message.from_user.id in config.ADMIN_IDS

admin_filter = filters.create(is_admin)

async def edit_admin_message(client: Client, callback_query: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup):
    """Edits the admin message correctly, whether it is a photo message or a text message."""
    message = callback_query.message
    try:
        if message.photo:
            await client.edit_message_caption(
                chat_id=message.chat.id,
                message_id=message.id,
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        else:
            await message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
    except RPCError as e:
        logger.error(f"Failed to edit admin message: {e}")

async def build_main_dashboard():
    """Generates the main dashboard text and keyboard markup."""
    settings = await db.get_settings()
    buttons = await db.get_buttons()
    
    photo = settings.get("photo_url_or_file_id")
    header = settings.get("header_text", "")
    body = settings.get("body_text", "")
    is_quote = settings.get("is_quote", 1)
    
    status_photo = "✅ Configured" if photo else "❌ Not set"
    status_quote = "✅ Enabled (blockquote)" if is_quote else "❌ Disabled (normal text)"
    
    text = (
        "🛠️ <b>BOT ADMIN CONTROL PANEL</b>\n\n"
        "Here you can customize the start screen that users see when they launch the bot.\n\n"
        f"<b>Current Settings:</b>\n"
        f"• <b>Start Photo:</b> {status_photo}\n"
        f"• <b>Quote Block:</b> {status_quote}\n"
        f"• <b>Header Text Length:</b> {len(header)} chars\n"
        f"• <b>Body Text Length:</b> {len(body)} chars\n"
        f"• <b>Total Inline Buttons:</b> {len(buttons)}\n\n"
        "<i>Use the buttons below to change configurations.</i>"
    )
    
    quote_toggle_label = "💬 Quote: ON" if is_quote else "💬 Quote: OFF"
    
    keyboard = [
        [
            InlineKeyboardButton("🖼️ Edit Photo", callback_data="admin_photo"),
            InlineKeyboardButton(quote_toggle_label, callback_data="admin_toggle_quote")
        ],
        [
            InlineKeyboardButton("✍️ Edit Header", callback_data="admin_header"),
            InlineKeyboardButton("📝 Edit Body", callback_data="admin_body")
        ],
        [
            InlineKeyboardButton("🎛️ Manage Buttons", callback_data="admin_buttons"),
            InlineKeyboardButton("👁️ Live Preview", callback_data="admin_preview")
        ],
        [
            InlineKeyboardButton("🏡 Back to Start Screen", callback_data="admin_close")
        ]
    ]
    
    return text, InlineKeyboardMarkup(keyboard)

@Client.on_message(filters.command("admin") & admin_filter & filters.private)
async def admin_menu_handler(client: Client, message: Message):
    """Initializes the admin panel."""
    await db.clear_admin_state(message.from_user.id)
    text, reply_markup = await build_main_dashboard()
    await message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

@Client.on_callback_query(filters.regex("^admin_") & filters.private)
async def admin_callbacks(client: Client, callback_query: CallbackQuery):
    """Handles callback interactions for the admin panel."""
    user_id = callback_query.from_user.id
    if user_id not in config.ADMIN_IDS:
        await callback_query.answer("⚠️ Access Denied", show_alert=True)
        return
        
    data = callback_query.data
    
    # Close Menu (Go back to user Start Screen)
    if data == "admin_close":
        await db.clear_admin_state(user_id)
        # Generate the normal start message for this admin user (with is_admin=True so they keep the entry button)
        text_content, photo, reply_markup = await generate_start_message(callback_query.from_user, is_admin=True)
        await edit_admin_message(client, callback_query, text_content, reply_markup)
        await callback_query.answer("Returned to Start Screen")
        return
        
    # Main Dashboard
    if data == "admin_main":
        await db.clear_admin_state(user_id)
        text, reply_markup = await build_main_dashboard()
        await edit_admin_message(client, callback_query, text, reply_markup)
        await callback_query.answer()
        return
        
    # Toggle Quote Styling
    if data == "admin_toggle_quote":
        settings = await db.get_settings()
        new_val = 0 if settings.get("is_quote", 1) else 1
        await db.update_setting_field("is_quote", new_val)
        text, reply_markup = await build_main_dashboard()
        await edit_admin_message(client, callback_query, text, reply_markup)
        await callback_query.answer("Quote style updated!")
        return
        
    # Edit Photo State Initiation
    if data == "admin_photo":
        await db.set_admin_state(user_id, "WAITING_FOR_PHOTO")
        await edit_admin_message(
            client,
            callback_query,
            text=(
                "📷 <b>EDIT START PHOTO</b>\n\n"
                "Send me the photo you want to display on <code>/start</code>.\n\n"
                "• You can **upload a photo** directly.\n"
                "• Or paste an **image URL** (direct link).\n"
                "• Send `/remove` to remove the photo and send text-only starts.\n\n"
                "<i>Send /cancel to discard changes and go back.</i>"
            ),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_main")]])
        )
        await callback_query.answer()
        return
        
    # Edit Header State Initiation
    if data == "admin_header":
        await db.set_admin_state(user_id, "WAITING_FOR_HEADER")
        await edit_admin_message(
            client,
            callback_query,
            text=(
                "✍️ <b>EDIT HEADER TEXT</b>\n\n"
                "Send me the new header text. This text is displayed outside the blockquote quotes.\n\n"
                "<b>Supported Placeholders:</b>\n"
                "• <code>{first_name}</code> - User's first name\n"
                "• <code>{last_name}</code> - User's last name\n"
                "• <code>{username}</code> - User's username (without @)\n"
                "• <code>{id}</code> - User's Telegram ID\n"
                "• <code>{mention}</code> - HTML profile link to user\n\n"
                "<i>Example: ✨ HI {first_name} WELCOME TO OUR BOT 👋</i>\n\n"
                "<i>Send /cancel to discard changes and go back.</i>"
            ),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_main")]])
        )
        await callback_query.answer()
        return
        
    # Edit Body State Initiation
    if data == "admin_body":
        await db.set_admin_state(user_id, "WAITING_FOR_BODY")
        await edit_admin_message(
            client,
            callback_query,
            text=(
                "📝 <b>EDIT BODY TEXT</b>\n\n"
                "Send me the new body text. If quote is enabled, this entire block will be inside a blockquote.\n\n"
                "<b>Supported Placeholders:</b>\n"
                "• <code>{first_name}</code>, <code>{last_name}</code>, <code>{username}</code>, <code>{id}</code>, <code>{mention}</code>\n\n"
                "<i>Send /cancel to discard changes and go back.</i>"
            ),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_main")]])
        )
        await callback_query.answer()
        return
        
    # Manage Buttons Menu
    if data == "admin_buttons":
        buttons = await db.get_buttons()
        text = "🎛️ <b>MANAGE START BUTTONS</b>\n\n"
        if not buttons:
            text += "<i>No buttons configured yet. Users will see standard start text only.</i>"
        else:
            text += "Here are the buttons currently shown to users (ordered by row):\n\n"
            for btn in buttons:
                b_type = "🔗 Link" if btn["type"] == "url" else "⚙️ Callback"
                text += f"• <b>{btn['label']}</b> (Row {btn['row']}) - <i>{b_type}</i>\n"
                text += f"   └ Value: <code>{btn['value']}</code>\n\n"
                
        # Generate keyboard showing active buttons with delete action next to them
        keyboard = []
        for btn in buttons:
            keyboard.append([
                InlineKeyboardButton(f"❌ Delete '{btn['label']}'", callback_data=f"admin_delete_btn_{btn['id']}")
            ])
            
        keyboard.append([InlineKeyboardButton("➕ Add New Button", callback_data="admin_add_button")])
        keyboard.append([InlineKeyboardButton("🔙 Back to Control Panel", callback_data="admin_main")])
        
        await edit_admin_message(
            client,
            callback_query,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await callback_query.answer()
        return
        
    # Add Button: Phase 1 (Label Input)
    if data == "admin_add_button":
        await db.set_admin_state(user_id, "WAITING_FOR_BTN_LABEL")
        await edit_admin_message(
            client,
            callback_query,
            text=(
                "➕ <b>ADD NEW BUTTON</b> (Step 1/3)\n\n"
                "Send me the label text for this button (e.g. <code>📚 Help</code> or <code>ℹ️ About</code>).\n\n"
                "<i>Send /cancel to cancel.</i>"
            ),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_buttons")]])
        )
        await callback_query.answer()
        return
        
    # Delete Button
    if data.startswith("admin_delete_btn_"):
        btn_id = int(data.split("_")[-1])
        await db.delete_button(btn_id)
        await callback_query.answer("Button deleted successfully!")
        
        # Refresh the buttons menu
        buttons = await db.get_buttons()
        text = "🎛️ <b>MANAGE START BUTTONS</b>\n\n"
        if not buttons:
            text += "<i>No buttons configured yet. Users will see standard start text only.</i>"
        else:
            text += "Here are the buttons currently shown to users (ordered by row):\n\n"
            for btn in buttons:
                b_type = "🔗 Link" if btn["type"] == "url" else "⚙️ Callback"
                text += f"• <b>{btn['label']}</b> (Row {btn['row']}) - <i>{b_type}</i>\n"
                text += f"   └ Value: <code>{btn['value']}</code>\n\n"
                
        keyboard = []
        for btn in buttons:
            keyboard.append([
                InlineKeyboardButton(f"❌ Delete '{btn['label']}'", callback_data=f"admin_delete_btn_{btn['id']}")
            ])
            
        keyboard.append([InlineKeyboardButton("➕ Add New Button", callback_data="admin_add_button")])
        keyboard.append([InlineKeyboardButton("🔙 Back to Control Panel", callback_data="admin_main")])
        
        await edit_admin_message(
            client,
            callback_query,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
        
    # Preview start screen
    if data == "admin_preview":
        await callback_query.answer("Generating preview...")
        text_content, photo, reply_markup = await generate_start_message(callback_query.from_user, is_admin=True)
        
        preview_header = "👀 <b>LIVE PREVIEW:</b>\n" + "─" * 20 + "\n\n"
        
        if photo:
            try:
                await client.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=preview_header + text_content,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            except RPCError as e:
                await callback_query.message.reply_text(
                    f"⚠️ <b>Failed to send preview with configured photo:</b>\n<code>{e}</code>\n\n"
                    f"Here is the text fallback preview:\n\n{text_content}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
        else:
            await client.send_message(
                chat_id=user_id,
                text=preview_header + text_content,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            
        # Re-send admin panel to keep it accessible
        text, reply_markup = await build_main_dashboard()
        await client.send_message(
            chat_id=user_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        return

# State handler for conversational inputs
@Client.on_message(filters.private & admin_filter)
async def admin_state_handlers(client: Client, message: Message):
    """Processes admin text/media inputs based on current database conversational state."""
    user_id = message.from_user.id
    state, context = await db.get_admin_state(user_id)
    
    if not state:
        # Not in any admin state, ignore (let other handlers parse commands like /start)
        return
        
    # Command bypass (e.g., if admin sends /start or /admin, clear state and let the command execute)
    if message.text and message.text.startswith("/") and message.text.strip() not in ("/cancel", "/remove"):
        await db.clear_admin_state(user_id)
        message.continue_propagation()
        
    # Cancel action
    if message.text and message.text.strip() == "/cancel":
        await db.clear_admin_state(user_id)
        await message.reply_text("❌ Action cancelled.")
        text, reply_markup = await build_main_dashboard()
        await message.reply_text(text=text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        return
        
    # 1. Processing Start Photo Change
    if state == "WAITING_FOR_PHOTO":
        photo_id = None
        if message.photo:
            # Direct photo upload
            photo_id = message.photo.file_id
        elif message.text:
            text_val = message.text.strip()
            if text_val == "/remove":
                photo_id = None
            elif text_val.startswith(("http://", "https://")):
                photo_id = text_val
            else:
                await message.reply_text("⚠️ Please send a valid photo or image URL starting with http/https.")
                return
        else:
            await message.reply_text("⚠️ Invalid input. Send a photo, an image URL, or /remove.")
            return
            
        await db.update_setting_field("photo_url_or_file_id", photo_id)
        await db.clear_admin_state(user_id)
        await message.reply_text("✅ Start Photo updated successfully!")
        
        # Reload admin control panel
        text, reply_markup = await build_main_dashboard()
        await message.reply_text(text=text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        return
        
    # 2. Processing Header Text Change
    if state == "WAITING_FOR_HEADER":
        if not message.text:
            await message.reply_text("⚠️ Header must be a text message. Please send text.")
            return
            
        header_text = message.text.strip()
        await db.update_setting_field("header_text", header_text)
        await db.clear_admin_state(user_id)
        await message.reply_text("✅ Header text updated successfully!")
        
        # Reload admin control panel
        text, reply_markup = await build_main_dashboard()
        await message.reply_text(text=text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        return
        
    # 3. Processing Body Text Change
    if state == "WAITING_FOR_BODY":
        if not message.text:
            await message.reply_text("⚠️ Body must be a text message. Please send text.")
            return
            
        body_text = message.text.strip()
        await db.update_setting_field("body_text", body_text)
        await db.clear_admin_state(user_id)
        await message.reply_text("✅ Body text updated successfully!")
        
        # Reload admin control panel
        text, reply_markup = await build_main_dashboard()
        await message.reply_text(text=text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        return
        
    # 4. Add Button Phase 1: Label Input completed
    if state == "WAITING_FOR_BTN_LABEL":
        if not message.text:
            await message.reply_text("⚠️ Label must be text. Please send text.")
            return
            
        btn_label = message.text.strip()
        context["label"] = btn_label
        await db.set_admin_state(user_id, "WAITING_FOR_BTN_VAL", context)
        await message.reply_text(
            f"➕ <b>ADD NEW BUTTON</b> (Step 2/3)\n\n"
            f"Label: <b>{btn_label}</b>\n\n"
            f"Now, send me the button value:\n"
            f"• Paste a link starting with http/https/tg for a <b>URL button</b>.\n"
            f"• Send a short text identifier for a <b>Callback button</b> (e.g. <code>about_cb</code>).\n\n"
            f"<i>Send /cancel to abort.</i>",
            parse_mode=ParseMode.HTML
        )
        return
        
    # 5. Add Button Phase 2: Value Input completed
    if state == "WAITING_FOR_BTN_VAL":
        if not message.text:
            await message.reply_text("⚠️ Value must be text. Please send text.")
            return
            
        btn_val = message.text.strip()
        context["value"] = btn_val
        
        # Ask for row number
        await db.set_admin_state(user_id, "WAITING_FOR_BTN_ROW", context)
        await message.reply_text(
            f"➕ <b>ADD NEW BUTTON</b> (Step 3/3)\n\n"
            f"Label: <b>{context['label']}</b>\n"
            f"Value: <code>{btn_val}</code>\n\n"
            f"Send me the row index for this button (e.g. <code>0</code>, <code>1</code>, <code>2</code>).\n"
            f"Buttons with the same row index will be grouped side-by-side in that row.\n\n"
            f"<i>Default: 0. Send /cancel to abort.</i>",
            parse_mode=ParseMode.HTML
        )
        return
        
    # 6. Add Button Phase 3: Row Input completed
    if state == "WAITING_FOR_BTN_ROW":
        row_idx = 0
        if message.text:
            val_strip = message.text.strip()
            if val_strip.isdigit():
                row_idx = int(val_strip)
            else:
                await message.reply_text("⚠️ Row must be a number (e.g. 0, 1, 2). Try again.")
                return
                
        btn_label = context["label"]
        btn_val = context["value"]
        
        # Infer type based on value structure
        btn_type = "url" if btn_val.startswith(("http://", "https://", "tg://")) else "callback"
        
        # Save to database
        await db.add_button(btn_label, btn_type, btn_val, row_idx)
        await db.clear_admin_state(user_id)
        
        await message.reply_text(
            f"✅ Button Added successfully!\n\n"
            f"• <b>Label:</b> {btn_label}\n"
            f"• <b>Type:</b> {btn_type.upper()}\n"
            f"• <b>Value:</b> {btn_val}\n"
            f"• <b>Row:</b> {row_idx}",
            parse_mode=ParseMode.HTML
        )
        
        # Show buttons list menu
        buttons = await db.get_buttons()
        text = "🎛️ <b>MANAGE START BUTTONS</b>\n\n"
        if not buttons:
            text += "<i>No buttons configured yet. Users will see standard start text only.</i>"
        else:
            text += "Here are the buttons currently shown to users (ordered by row):\n\n"
            for btn in buttons:
                b_type = "🔗 Link" if btn["type"] == "url" else "⚙️ Callback"
                text += f"• <b>{btn['label']}</b> (Row {btn['row']}) - <i>{b_type}</i>\n"
                text += f"   └ Value: <code>{btn['value']}</code>\n\n"
                
        keyboard = []
        for btn in buttons:
            keyboard.append([
                InlineKeyboardButton(f"❌ Delete '{btn['label']}'", callback_data=f"admin_delete_btn_{btn['id']}")
            ])
            
        keyboard.append([InlineKeyboardButton("➕ Add New Button", callback_data="admin_add_button")])
        keyboard.append([InlineKeyboardButton("🔙 Back to Control Panel", callback_data="admin_main")])
        
        await message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
