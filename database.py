import os
import json
import aiosqlite
import logging

DB_PATH = os.path.join(os.path.dirname(__file__), "bot_data.db")
logger = logging.getLogger(__name__)

async def init_db():
    """Initializes the database and sets up default configuration if empty."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Create bot_settings table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                id INTEGER PRIMARY KEY,
                photo_url_or_file_id TEXT,
                header_text TEXT,
                body_text TEXT,
                is_quote INTEGER DEFAULT 1
            )
        """)
        
        # Create buttons table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS buttons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                type TEXT NOT NULL, -- 'url' or 'callback'
                value TEXT NOT NULL, -- URL link or callback query payload
                row INTEGER DEFAULT 0
            )
        """)
        
        # Create admin_state table for conversational state machine
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admin_state (
                user_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                context TEXT -- JSON serialized dictionary for extra parameters
            )
        """)
        
        await db.commit()
        
        # Check if settings are already initialized
        async with db.execute("SELECT COUNT(*) FROM bot_settings") as cursor:
            row = await cursor.fetchone()
            if row[0] == 0:
                # Insert default settings
                default_header = "✨ HI {first_name} WELCOME TO OUR BOT 👋"
                default_body = (
                    "🎯 I'M AN ADVANCED FORWARD BOT WITH SPECIAL FEATURES\n\n"
                    "⚡ CLICK THE BUTTONS BELOW TO EXPLORE MORE"
                )
                await db.execute(
                    """
                    INSERT INTO bot_settings (id, photo_url_or_file_id, header_text, body_text, is_quote)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (1, None, default_header, default_body, 1)
                )
                
                # Add some default buttons
                default_buttons = [
                    ("📚 Help", "url", "https://t.me/telegram", 0),
                    ("ℹ️ About", "callback", "about_cb", 0),
                    ("⚙️ Settings", "callback", "settings_cb", 1),
                    ("📊 Status", "callback", "status_cb", 1),
                    ("🔗 How to Use", "url", "https://t.me/telegram", 2)
                ]
                
                for label, type_, val, row_idx in default_buttons:
                    await db.execute(
                        "INSERT INTO buttons (label, type, value, row) VALUES (?, ?, ?, ?)",
                        (label, type_, val, row_idx)
                    )
                
                await db.commit()
                logger.info("Database initialized with default configurations.")

async def get_settings():
    """Fetches the current bot settings."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bot_settings WHERE id = 1") as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
    return None

async def update_setting_field(field_name: str, value):
    """Updates a single setting field in bot_settings."""
    allowed_fields = {"photo_url_or_file_id", "header_text", "body_text", "is_quote"}
    if field_name not in allowed_fields:
        raise ValueError(f"Invalid field: {field_name}")
        
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE bot_settings SET {field_name} = ? WHERE id = 1",
            (value,)
        )
        await db.commit()
        logger.info(f"Updated setting field '{field_name}' successfully.")

async def get_buttons():
    """Fetches all customized inline buttons ordered by row and id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM buttons ORDER BY row ASC, id ASC") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def add_button(label: str, type_: str, value: str, row: int = 0):
    """Adds a new button to the start keyboard."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO buttons (label, type, value, row) VALUES (?, ?, ?, ?)",
            (label, type_, value, row)
        )
        await db.commit()
        logger.info(f"Added new button: '{label}'")

async def delete_button(button_id: int):
    """Removes a button from the start keyboard."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM buttons WHERE id = ?", (button_id,))
        await db.commit()
        logger.info(f"Deleted button ID: {button_id}")

async def get_admin_state(user_id: int):
    """Retrieves the admin state and context context."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT state, context FROM admin_state WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                state, context_str = row
                context = json.loads(context_str) if context_str else {}
                return state, context
    return None, {}

async def set_admin_state(user_id: int, state: str, context: dict = None):
    """Saves the admin state and optional JSON context."""
    context_str = json.dumps(context) if context else None
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO admin_state (user_id, state, context)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET state=excluded.state, context=excluded.context
            """,
            (user_id, state, context_str)
        )
        await db.commit()
        logger.info(f"Admin {user_id} state set to {state}")

async def clear_admin_state(user_id: int):
    """Clears the admin state."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admin_state WHERE user_id = ?", (user_id,))
        await db.commit()
        logger.info(f"Admin {user_id} state cleared.")
