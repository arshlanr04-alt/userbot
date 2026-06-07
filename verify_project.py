import sys
import asyncio
import logging

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Verification")

async def verify():
    logger.info("Starting verification...")
    
    # Try importing modules
    try:
        import config
        logger.info("✅ config.py imported successfully.")
    except Exception as e:
        logger.critical(f"❌ Failed to import config.py: {e}")
        return False
        
    try:
        import database as db
        logger.info("✅ database.py imported successfully.")
    except Exception as e:
        logger.critical(f"❌ Failed to import database.py: {e}")
        return False
        
    try:
        import start_handler
        logger.info("✅ start_handler.py imported successfully.")
    except Exception as e:
        logger.critical(f"❌ Failed to import start_handler.py: {e}")
        return False
        
    try:
        import admin_panel
        logger.info("✅ admin_panel.py imported successfully.")
    except Exception as e:
        logger.critical(f"❌ Failed to import admin_panel.py: {e}")
        return False
        
    try:
        import main
        logger.info("✅ main.py imported successfully.")
    except Exception as e:
        logger.critical(f"❌ Failed to import main.py: {e}")
        return False
        
    # Check database initialization
    logger.info("Testing database initialization...")
    try:
        await db.init_db()
        logger.info("✅ Database initialized successfully.")
        
        settings = await db.get_settings()
        if settings:
            logger.info("✅ Settings table verified. Initial settings fetched successfully.")
            logger.info(f"   Settings details: {settings}")
        else:
            logger.error("❌ Database settings table empty after initialization.")
            return False
            
        buttons = await db.get_buttons()
        logger.info(f"✅ Buttons table verified. Loaded {len(buttons)} default buttons.")
        for btn in buttons:
            logger.info(f"   Button: {btn['label']} | Type: {btn['type']} | Value: {btn['value']} | Row: {btn['row']}")
            
    except Exception as e:
        logger.critical(f"❌ Database verification failed: {e}", exc_info=True)
        return False
        
    logger.info("🎉 Verification Complete! All modules imported successfully and database tables verified.")
    return True

if __name__ == "__main__":
    success = asyncio.run(verify())
    sys.exit(0 if success else 1)
