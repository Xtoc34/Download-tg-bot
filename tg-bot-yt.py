#!/usr/bin/env python3
"""
Telegram Video Downloader Bot
Main entry point
"""

import logging
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)

# Import configuration
from config import TELEGRAM_TOKEN, ADMIN_IDS, WEBHOOK_URL, LOGLEVEL, PORT, DB_PATH

# Import database
from database import init_db, create_access_code

# Import handlers
from handlers import (
    start, help_cmd, language_cmd, language_callback, history_cmd,
    handle_message, quality_callback, code_cmd, stats_cmd,
    create_code_cmd, list_codes_cmd, deactivate_code_cmd
)

# Setup logging
logging.basicConfig(
    level=LOGLEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Main bot entry point"""
    
    # Check token
    if not TELEGRAM_TOKEN:
        print('❌ Please set TELEGRAM_TOKEN environment variable')
        return
    
    # Initialize database
    init_db()
    
    # Check and create default access codes
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM access_codes')
    code_count = cur.fetchone()[0]
    conn.close()
    
    if code_count == 0:
        if ADMIN_IDS:
            default_code = create_access_code('ADMIN2026')
            logger.info(f'📝 Admin access code created: {default_code}')
            print(f'📝 Admin access code: {default_code}')
            print(f'📝 Use /create_code YOURCODE to create more codes')
        else:
            default_code = create_access_code('WELCOME123')
            logger.info(f'📝 Default access code created: {default_code}')
            print(f'📝 Default access code: {default_code}')
            print(f'⚠️ Set ADMIN_IDS to your Telegram user ID for admin access')
    
    # Build application
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(CommandHandler('language', language_cmd))
    app.add_handler(CommandHandler('history', history_cmd))
    app.add_handler(CommandHandler('code', code_cmd))
    app.add_handler(CommandHandler('stats', stats_cmd))
    app.add_handler(CommandHandler('create_code', create_code_cmd))
    app.add_handler(CommandHandler('list_codes', list_codes_cmd))
    app.add_handler(CommandHandler('deactivate_code', deactivate_code_cmd))
    app.add_handler(CallbackQueryHandler(language_callback, pattern=r'lang_'))
    app.add_handler(CallbackQueryHandler(quality_callback, pattern=r'quality_'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Run bot
    if WEBHOOK_URL:
        logger.info(f'🤖 Starting webhook mode on port {PORT} with URL {WEBHOOK_URL}')
        app.run_webhook(listen='0.0.0.0', port=PORT, webhook_url=WEBHOOK_URL)
    else:
        logger.info('🤖 Starting polling mode')
        app.run_polling()


if __name__ == '__main__':
    main()
