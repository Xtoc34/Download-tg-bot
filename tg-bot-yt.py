import os
import re
import asyncio
import sqlite3
import logging
import tempfile
import shutil
from datetime import datetime

from yt_dlp import YoutubeDL
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

LOGLEVEL = os.getenv('LOGLEVEL', 'INFO')
logging.basicConfig(
    level=LOGLEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DB_PATH = 'history.db'
DOWNLOADS_DIR = 'downloads'
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

YTDLP_COOKIES = os.getenv('YTDLP_COOKIES')
YTDLP_PROXY = os.getenv('YTDLP_PROXY')

URL_RE = re.compile(r'https?://\S+')


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        url TEXT,
        ts TEXT,
        status TEXT,
        filename TEXT,
        quality TEXT
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS user_settings (
        user_id INTEGER PRIMARY KEY,
        language TEXT DEFAULT 'ru'
    )''')
    conn.commit()
    conn.close()


def get_user_language(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT language FROM user_settings WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 'ru'


def set_user_language(user_id, lang):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('INSERT OR REPLACE INTO user_settings (user_id, language) VALUES (?, ?)', (user_id, lang))
    conn.commit()
    conn.close()


# Translations dictionary
TRANSLATIONS = {
    'ru': {
        'hello': 'Привет! 👋 Я скачиваю видео с YouTube, Instagram, TikTok и других сайтов.\n\nПросто отправьте мне ссылку, выберите качество — и получите видео!\n\nКоманды:\n/history — просмотреть историю загрузок\n/help — справка\n/language — выбрать язык',
        'help_intro': '📌 Как пользоваться:',
        'help_text': '1. Отправьте ссылку (YouTube, Instagram, TikTok и др.)\n2. Выберите качество:\n   🟢 144p — самый лёгкий\n   ⚡ 240p — быстро\n   📹 360p — нормальное\n   🎬 HD — лучшее\n3. Ждите загрузки 📥',
        'limit': '⚠️ Лимит Telegram: макс 50MB за раз',
        'support_text': 'Поддержка / Support',
        'choose_quality': 'Выберите качество:',
        'empty_history': 'История пустая.',
        'history_title': '📋 Ваша история (последние 15):',
        'invalid_url': '❌ Пожалуйста, пришлите ссылку (YouTube, Instagram, TikTok и др.).',
        'downloading': '⏳ Скачиваю видео ({quality}p)...',
        'uploading': '📤 Загружаю "{title}"... ({size}MB)',
        'file_too_large': '⚠️ Файл {size}MB слишком большой (лимит 50MB).\nСсылка для прямой загрузки:\n{url}',
        'error_timeout': '⏱️ Истёк лимит времени. Попробуйте 360p или позже.',
        'error_unavailable': '🔒 Видео недоступно (приватное, удалено или по геоблоку).',
        'error_general': '❌ Ошибка: {error}',
        'language_set': 'Язык изменён на Русский 🇷🇺',
        'quality_144': '🟢 144p (мини)',
        'quality_240': '⚡ 240p (быстро)',
        'quality_360': '📹 360p (обычно)',
        'quality_hd': '🎬 HD (лучше)',
    },
    'en': {
        'hello': 'Hello! 👋 I download videos from YouTube, Instagram, TikTok and other sites.\n\nJust send me a link, choose quality — and get your video!\n\nCommands:\n/history — view download history\n/help — help\n/language — choose language',
        'help_intro': '📌 How to use:',
        'help_text': '1. Send a link (YouTube, Instagram, TikTok, etc.)\n2. Choose quality:\n   🟢 144p — smallest\n   ⚡ 240p — fast\n   📹 360p — normal\n   🎬 HD — best\n3. Wait for upload 📥',
        'limit': '⚠️ Telegram limit: max 50MB at a time',
        'support_text': 'Support / Поддержка',
        'choose_quality': 'Choose quality:',
        'empty_history': 'History is empty.',
        'history_title': '📋 Your history (last 15):',
        'invalid_url': '❌ Please send a link (YouTube, Instagram, TikTok, etc.).',
        'downloading': '⏳ Downloading video ({quality}p)...',
        'uploading': '📤 Uploading "{title}"... ({size}MB)',
        'file_too_large': '⚠️ File {size}MB is too large (limit 50MB).\nDirect download link:\n{url}',
        'error_timeout': '⏱️ Time limit exceeded. Try 360p or later.',
        'error_unavailable': '🔒 Video unavailable (private, deleted or geo-blocked).',
        'error_general': '❌ Error: {error}',
        'language_set': 'Language changed to English 🇬🇧',
        'quality_144': '🟢 144p (mini)',
        'quality_240': '⚡ 240p (fast)',
        'quality_360': '📹 360p (normal)',
        'quality_hd': '🎬 HD (better)',
    }
}


def t(user_id, key, **kwargs):
    """Get translation for user's language"""
    lang = get_user_language(user_id)
    text = TRANSLATIONS.get(lang, TRANSLATIONS['ru']).get(key, key)
    return text.format(**kwargs) if kwargs else text


def add_history(user_id, username, url, status='pending', filename=None, quality=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    ts = datetime.utcnow().isoformat()
    cur.execute('INSERT INTO history (user_id, username, url, ts, status, filename, quality) VALUES (?,?,?,?,?,?,?)',
                (user_id, username, url, ts, status, filename, quality))
    rowid = cur.lastrowid
    conn.commit()
    conn.close()
    return rowid


def update_history(rowid, status, filename=None, quality=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('UPDATE history SET status = ?, filename = ?, quality = ? WHERE id = ?', (status, filename, quality, rowid))
    conn.commit()
    conn.close()


def get_history_for_user(user_id, limit=20):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT id, url, ts, status, filename, quality FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?', (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows


def is_url(text: str) -> bool:
    return bool(URL_RE.search(text))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = t(user.id, 'hello')
    await update.message.reply_text(msg)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    support = os.getenv('SUPPORT_BOT')
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
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton('🇷🇺 Русский', callback_data=f'lang_ru_{user.id}')],
        [InlineKeyboardButton('🇬🇧 English', callback_data=f'lang_en_{user.id}')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    current_lang = get_user_language(user.id)
    msg = f'Current language / Текущий язык: {current_lang}\n\nChoose / Выберите:'
    await update.message.reply_text(msg, reply_markup=reply_markup)


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if lang not in TRANSLATIONS:
        await query.edit_message_text('Invalid language.')
        return
    set_user_language(user_id, lang)
    await query.edit_message_text(t(user_id, 'language_set'))


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    rows = get_history_for_user(user.id)
    if not rows:
        await update.message.reply_text(t(user.id, 'empty_history'))
        return
    lines = []
    for r in rows:
        rid, url, ts, status, filename, quality = r
        short_url = url[:40] + '...' if len(url) > 40 else url
        quality_str = quality if quality else '-'
        lines.append(f'[{rid}] {status.upper()} | {quality_str}p\n{short_url}\n{ts[:10]}\n')
    text = '\n'.join(lines[:15])
    await update.message.reply_text(f'{t(user.id, "history_title")}\n\n{text}')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(t(user.id, 'choose_quality'), reply_markup=reply_markup)


async def quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    quality = parts[1]
    rowid = int(parts[2])
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT url FROM history WHERE id = ?', (rowid,))
    row = cur.fetchone()
    conn.close()
    
    if not row:
        await query.edit_message_text('❌ Ошибка: запрос не найден.')
        return
    
    url = row[0]
    await query.edit_message_text(f'⏳ Скачиваю видео ({quality}p)...')
    asyncio.create_task(download_and_send(url, query, context, rowid, quality))


async def download_and_send(url, query, context: ContextTypes.DEFAULT_TYPE, rowid: int, quality: str):
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    
    tempdir = tempfile.mkdtemp(dir=DOWNLOADS_DIR)
    
    quality_formats = {
        '144': 'worst[height<=144][ext=mp4]/worst',
        '240': 'worst[height<=240][ext=mp4]/worst',
        '360': 'worst[height<=360][ext=mp4]/worst',
        '720': 'best[height<=720][ext=mp4]/best[height<=720]/best[ext=mp4]',
        'hd': 'best[ext=mp4]/best'
    }
    
    ydl_opts = {
        'format': quality_formats.get(quality, 'best[ext=mp4]'),
        'outtmpl': os.path.join(tempdir, '%(id)s.%(ext)s'),
        'noplaylist': True,
        'quiet': False,
        'socket_timeout': 60,
        'http_chunk_size': 1024 * 1024,
        'throttledratelimit': 100 * 1024,
    }

    if YTDLP_COOKIES:
        cookies_path = os.path.join(tempdir, 'cookies.txt')
        with open(cookies_path, 'w', encoding='utf-8') as cookie_file:
            cookie_file.write(YTDLP_COOKIES)
        ydl_opts['cookiefile'] = cookies_path
        logger.info('Using cookies from YTDLP_COOKIES')

    if YTDLP_PROXY:
        ydl_opts['proxy'] = YTDLP_PROXY
        logger.info('Using proxy from YTDLP_PROXY')
    
    try:
        logger.info(f'Downloading {url} with quality {quality}')
        
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
        
        if not os.path.exists(filepath):
            update_history(rowid, 'failed', quality=quality)
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text='❌ Файл не найден после скачивания.'
            )
            return
        
        size = os.path.getsize(filepath)
        title = info.get('title', 'Video')
        
        if size > 50 * 1024 * 1024:
            direct_url = info.get('url') or None
            if not direct_url and isinstance(info.get('formats'), list):
                for fmt in reversed(info['formats']):
                    if fmt.get('url'):
                        direct_url = fmt['url']
                        break

            message_text = f'⚠️ Файл {size // (1024*1024)}MB слишком большой для отправки по Telegram (лимит 50MB).'
            if direct_url:
                message_text += f'\nСсылка для прямой загрузки:\n{direct_url}'
            else:
                message_text += '\nПопробуйте найти файл по ссылке в браузере или использовать качество 360p.'

            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=message_text
            )
            update_history(rowid, 'too_large', quality=quality)
            return
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f'📤 Загружаю "{title[:30]}"... ({size // (1024*1024)}MB)'
        )
        
        with open(filepath, 'rb') as video_file:
            await context.bot.send_video(
                chat_id=chat_id,
                video=video_file,
                caption=f'✅ {title[:60]}\n📊 {size // (1024*1024)}MB | {quality}p'
            )
        
        update_history(rowid, 'done', os.path.basename(filepath), quality=quality)
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f'Successfully downloaded {url}')
        
    except Exception as e:
        logger.exception(f'Download failed for {url}: {e}')
        update_history(rowid, 'failed', quality=quality)
        
        error_msg = str(e).lower()
        if 'timed out' in error_msg or 'timeout' in error_msg:
            msg = '⏱️ Истёк лимит времени. Попробуйте 360p или позже.'
        elif 'not available' in error_msg:
            msg = '🔒 Видео недоступно (приватное, удалено или по геоблоку).'
        else:
            msg = f'❌ Ошибка: {str(e)[:80]}'
        
        await context.bot.send_message(chat_id=chat_id, text=msg)
        
    finally:
        try:
            shutil.rmtree(tempdir)
        except Exception as e:
            logger.warning(f'Failed to clean temp dir: {e}')


def main():
    init_db()
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        print('❌ Please set TELEGRAM_TOKEN environment variable')
        return
    
    app = ApplicationBuilder().token(token).build()
    
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(CommandHandler('language', language_cmd))
    app.add_handler(CommandHandler('history', history_cmd))
    app.add_handler(CallbackQueryHandler(language_callback, pattern=r'lang_'))
    app.add_handler(CallbackQueryHandler(quality_callback, pattern=r'quality_'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info('🤖 Bot started successfully!')
    app.run_polling()


if __name__ == '__main__':
    main()

