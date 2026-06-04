import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import ADMIN_IDS, SUPPORT_BOT
from database import (
    is_user_authorized, get_history_for_user, add_history,
    set_user_language, get_user_language, authorize_user,
    create_access_code, validate_access_code, get_all_access_codes,
    deactivate_access_code, get_user_stats, log_user_request
)
from decorators import requires_auth
from translations import t
from utils import is_url, truncate_text
from download import download_and_send

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    
    if is_user_authorized(user.id) or user.id in ADMIN_IDS:
        msg = t(user.id, 'hello')
        await update.message.reply_text(msg)
    else:
        msg = t(user.id, 'access_required')
        await update.message.reply_text(msg)


@requires_auth
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    user = update.effective_user
    support = SUPPORT_BOT
    support_line = ''
    if support:
        s = support if support.startswith('@') else f'@{support}'
        support_line = f"\n{t(user.id, 'support_text')}: {s}"

    msg = f'''{t(user.id, 'help_intro')}
{t(user.id, 'help_text')}

{t(user.id, 'limit')}{support_line}
'''
    await update.message.reply_text(msg)


async def language_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /language command - available to all users"""
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton('Русский', callback_data=f'lang_ru_{user.id}')],
        [InlineKeyboardButton('🇺🇦 Українська', callback_data=f'lang_ua_{user.id}')],
        [InlineKeyboardButton('🇬🇧 English', callback_data=f'lang_en_{user.id}')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    current_lang = get_user_language(user.id)
    msg = f'Current language / Поточна мова / Текущий язык: {current_lang}\n\nChoose / Обрати / Выберите:'
    await update.message.reply_text(msg, reply_markup=reply_markup)


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle language selection callback"""
    query = update.callback_query
    await query.answer()
    parts = query.data.split('_')
    if len(parts) < 3:
        await query.edit_message_text('Invalid language selection.')
        return
    lang = parts[1]
    user_id = int(parts[2])
    if query.from_user.id != user_id:
        await query.answer('This button is not for you.', show_alert=True)
        return
    if lang not in ['ru', 'en', 'ua']:
        await query.edit_message_text('Invalid language.')
        return
    set_user_language(user_id, lang)
    await query.edit_message_text(t(user_id, 'language_set'))


@requires_auth
async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history command - disabled"""
    user = update.effective_user
    await update.message.reply_text('📋 История запросов отключена.')


@requires_auth
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages with URLs"""
    text = update.message.text.strip()
    user = update.effective_user
    
    if not is_url(text):
        await update.message.reply_text(t(user.id, 'invalid_url'))
        return
    
    rowid = add_history(user.id, user.username or '', text)
    
    keyboard = [
        [
            InlineKeyboardButton(t(user.id, 'quality_144'), callback_data=f'quality_144_{rowid}'),
            InlineKeyboardButton(t(user.id, 'quality_240'), callback_data=f'quality_240_{rowid}'),
        ],
        [
            InlineKeyboardButton(t(user.id, 'quality_360'), callback_data=f'quality_360_{rowid}'),
            InlineKeyboardButton(t(user.id, 'quality_hd'), callback_data=f'quality_hd_{rowid}'),
        ],
        [
            InlineKeyboardButton(t(user.id, 'quality_audio'), callback_data=f'quality_audio_{rowid}')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(t(user.id, 'choose_quality'), reply_markup=reply_markup)


async def quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quality selection"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not is_user_authorized(user_id) and user_id not in ADMIN_IDS:
        await query.answer(t(user_id, 'access_required'), show_alert=True)
        return
    
    parts = query.data.split('_')
    quality = parts[1]
    rowid = int(parts[2])
    
    from database import sqlite3, DB_PATH
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT url FROM history WHERE id = ?', (rowid,))
    row = cur.fetchone()
    conn.close()
    
    if not row:
        await query.edit_message_text('❌ Error: request not found.')
        return
    
    url = row[0]
    label = f'{quality}p' if quality != 'audio' else 'audio'
    await query.edit_message_text(f'⏳ Скачиваю {"аудио" if quality == "audio" else "видео"} ({label})...')
    asyncio.create_task(download_and_send(url, query, context, rowid, quality))


async def code_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /code command for access codes"""
    user_id = update.effective_user.id
    
    if is_user_authorized(user_id):
        await update.message.reply_text(t(user_id, 'code_accepted'))
        return
    
    if not context.args:
        await update.message.reply_text(t(user_id, 'access_required'))
        return
    
    code = context.args[0].upper()
    
    if validate_access_code(code):
        authorize_user(user_id, update.effective_user.username)
        await update.message.reply_text(t(user_id, 'code_accepted'))
        msg = t(user_id, 'hello')
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text(t(user_id, 'code_invalid'))


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command (admin only)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(t(user_id, 'not_admin'))
        return
    
    stats = get_user_stats()
    
    # Admin messages always in Russian
    ru = {'admin_stats': '📊 Статистика бота:'}
    stats_text = f"""{ru['admin_stats']}

👥 Пользователи:
   Всего авторизовано: {stats['total_users']}
   Зарегистрировано: {stats['total_registered']}
   Активных сегодня: {stats['active_today']}

🔥 Топ пользователей по запросам:"""
    
    for user_data in stats['top_users']:
        uid, username, count, last_active = user_data
        username_str = username if username else f"user_{uid}"
        stats_text += f"\n   @{username_str}: {count} запросов"
    
    stats_text += "\n\n📊 Популярные команды:"
    for cmd, count in stats['command_stats']:
        stats_text += f"\n   {cmd}: {count}"
    
    await update.message.reply_text(stats_text)


async def create_code_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /create_code command (admin only)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(t(user_id, 'not_admin'))
        return
    
    code = context.args[0].upper() if context.args else None
    new_code = create_access_code(code)
    
    await update.message.reply_text(t(user_id, 'code_created', code=new_code))


async def list_codes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /list_codes command (admin only)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(t(user_id, 'not_admin'))
        return
    
    codes = get_all_access_codes()
    
    if not codes:
        await update.message.reply_text("Коды доступа не созданы.")
        return
    
    codes_text = f"{t(user_id, 'admin_codes')}\n\n"
    for code, created_at, used_by, is_active in codes:
        status = "✅ Активен" if is_active else "❌ Деактивирован"
        codes_text += f"Код: `{code}`\nСоздан: {created_at[:10]}\nИспользован: {used_by} раз(а)\nСтатус: {status}\n\n"
    
    await update.message.reply_text(codes_text)


async def deactivate_code_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /deactivate_code command (admin only)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(t(user_id, 'not_admin'))
        return
    
    if not context.args:
        await update.message.reply_text("Используйте: /deactivate_code <код>")
        return
    
    code = context.args[0].upper()
    deactivate_access_code(code)
    
    await update.message.reply_text(t(user_id, 'code_deactivated'))
