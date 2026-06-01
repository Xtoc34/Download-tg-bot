from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_IDS
from database import is_user_authorized, log_user_request
from translations import t


def requires_auth(func):
    """Decorator to check user authorization"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        
        # Admins always have access
        if user_id in ADMIN_IDS:
            return await func(update, context, *args, **kwargs)
        
        if not is_user_authorized(user_id):
            await update.message.reply_text(t(user_id, 'access_required'))
            return
        
        # Log the request
        log_user_request(user_id, update.message.text if update.message else 'callback')
        
        return await func(update, context, *args, **kwargs)
    return wrapper
