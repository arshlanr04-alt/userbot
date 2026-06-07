# Customizable Telegram Start Bot

A premium, database-backed Telegram bot/userbot built using Pyrogram. This bot allows administrators to interactively customize the `/start` greeting screen (including text, photo, blockquote styling, and inline buttons) via a premium inline-button dashboard.

---

## Features

- 🛠️ **Premium Admin Panel:** Control everything dynamically using inline menus via the `/admin` command.
- 🖼️ **Custom Start Photo:** Upload a photo directly or provide an image URL.
- 📝 **Dynamic Templates:** Personalize greetings using placeholders like `{first_name}`, `{mention}`, etc.
- 💬 **Blockquote Formatting:** Toggle blockquote style rendering (`<blockquote>` or quote quotes format) for the main body.
- 🎛️ **Custom Inline Keyboard:** Add, delete, and group inline URL links or Callback buttons in grid rows.
- 🤖 **Dual Mode:** Runs either as a standard Bot (using a token) or a Userbot (acting on a user account).

---

## Setup Instructions

### 1. Install Dependencies
Ensure you have Python 3.8+ installed, then install the required libraries:
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.template` to a new file named `.env` and fill in the details:
```bash
cp .env.template .env
```

Open `.env` and configure:
- `API_ID` & `API_HASH`: Get these from [my.telegram.org](https://my.telegram.org).
- `BOT_TOKEN`: Get this from [@BotFather](https://t.me/BotFather) (for bot mode). If omitted, the client runs in **Userbot mode** (using your phone number).
- `ADMIN_IDS`: A comma-separated list of Telegram User IDs allowed to access the admin panel.

### 3. Start the Bot
Run the main startup script:
```bash
python main.py
```
*(If running in Userbot mode for the first time, it will prompt you in the console to enter your phone number and the login code sent by Telegram).*

---

## How to Customize

### Placeholders (Supported in Header and Body)
You can include these placeholders in your texts. They will be dynamically replaced when a user presses `/start`:
- `{first_name}` - User's first name (HTML-escaped)
- `{last_name}` - User's last name (HTML-escaped)
- `{username}` - User's username (without `@`)
- `{id}` - User's Telegram ID
- `{mention}` - Direct link to the user's profile mentioning their first name

### Admin Panel Commands
- `/admin` - Opens the interactive administration control dashboard (accessible only by IDs listed in `ADMIN_IDS`).
- `/cancel` - Discards changes and returns to the main control panel when typing settings.
- `/remove` - Removes the start photo when configuring the photo option.
