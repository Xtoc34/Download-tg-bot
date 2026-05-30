import os
import re
import asyncio
import sqlite3
import logging
import tempfile
import shutil
import secrets
from datetime import datetime
from functools import wraps

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

# Администраторы бота (добавьте свои ID через запятую)
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip().isdigit()]

YTDLP_COOKIES = os.getenv('YTDLP_COOKIES')
YTDLP_PROXY = os.getenv('YTDLP_PROXY')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

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
        language TEXT DEFAULT 'ru',
        is_authorized INTEGER DEFAULT 0,
        first_seen TEXT,
        last_active TEXT,
        request_count INTEGER DEFAULT 0
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS access_codes (
        code TEXT PRIMARY KEY,
        created_at TEXT,
        used_by INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS user_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        command TEXT,
        ts TEXT
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


def is_user_authorized(user_id):
    """Проверка, авторизован ли пользователь"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT is_authorized FROM user_settings WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] == 1 if row else False


def authorize_user(user_id, username=None):
    """Авторизация пользователя"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute('''INSERT OR REPLACE INTO user_settings 
                   (user_id, language, is_authorized, first_seen, last_active, request_count) 
                   VALUES (?, COALESCE((SELECT language FROM user_settings WHERE user_id = ?), 'ru'), 1, 
                   COALESCE((SELECT first_seen FROM user_settings WHERE user_id = ?), ?), ?, 
                   COALESCE((SELECT request_count FROM user_settings WHERE user_id = ?), 0))''',
                (user_id, user_id, user_id, now, now, user_id))
    conn.commit()
    conn.close()


def log_user_request(user_id, command):
    """Логирование запроса пользователя"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute('INSERT INTO user_requests (user_id, command, ts) VALUES (?, ?, ?)', (user_id, command, now))
    cur.execute('UPDATE user_settings SET last_active = ?, request_count = request_count + 1 WHERE user_id = ?', (now, user_id))
    conn.commit()
    conn.close()


def create_access_code(code=None):
    """Создание кода доступа"""
    if not code:
        code = secrets.token_urlsafe(8).upper()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute('INSERT OR IGNORE INTO access_codes (code, created_at, is_active) VALUES (?, ?, 1)', (code, now))
    conn.commit()
    conn.close()
    return code


def validate_access_code(code):
    """Проверка кода доступа"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT is_active FROM access_codes WHERE code = ?', (code,))
    row = cur.fetchone()
    if row and row[0] == 1:
        cur.execute('UPDATE access_codes SET used_by = used_by + 1 WHERE code = ?', (code,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False


def get_all_access_codes():
    """Получение всех кодов доступа"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT code, created_at, used_by, is_active FROM access_codes ORDER BY created_at DESC')
    rows = cur.fetchall()
    conn.close()
    return rows


def deactivate_access_code(code):
    """Деактивация кода доступа"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('UPDATE access_codes SET is_active = 0 WHERE code = ?', (code,))
    conn.commit()
    conn.close()


def get_user_stats():
    """Получение статистики пользователей"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Общая статистика
    cur.execute('SELECT COUNT(*) FROM user_settings WHERE is_authorized = 1')
    total_users = cur.fetchone()[0]
    
    cur.execute('SELECT COUNT(*) FROM user_settings')
    total_registered = cur.fetchone()[0]
    
    # Активные за сегодня
    today = datetime.utcnow().date().isoformat()
    cur.execute('SELECT COUNT(DISTINCT user_id) FROM user_requests WHERE ts LIKE ?', (f'{today}%',))
    active_today = cur.fetchone()[0]
    
    # Топ пользователей по запросам
    cur.execute('''SELECT user_id, username, request_count, last_active 
                   FROM user_settings 
                   WHERE is_authorized = 1 
                   ORDER BY request_count DESC LIMIT 10''')
    top_users = cur.fetchall()
    
    # Статистика по командам
    cur.execute('''SELECT command, COUNT(*) as count 
                   FROM user_requests 
                   GROUP BY command 
                   ORDER BY count DESC LIMIT 10''')
    command_stats = cur.fetchall()
    
    conn.close()
    return {
        'total_users': total_users,
        'total_registered': total_registered,
        'active_today': active_today,
        'top_users': top_users,
        'command_stats': command_stats
    }


# Translations dictionary
TRANSLATIONS = {
    'ru': {
        'hello': 'Привет! 👋 Я скачиваю видео с YouTube, Instagram, TikTok и других сайтов.\n\nПросто отправьте мне ссылку, выберите качество — и получите видео!\n\nКоманды:\n/history — просмотреть историю загрузок\n/help — справка\n/language — выбрать язык',
        'help_intro': '📌 Как пользоваться:',
        'help_text': '1. Отправьте ссылку (YouTube, Instagram, TikTok и др.)\n2. Выберите качество:\n   🟢 144p — самый лёгкий\n   ⚡ 240p — быстро\n   📹 360p — нормальное\n   🎬 HD — лучшее\n   🎵 Аудио — только звук\n3. Ждите загрузки 📥',
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
        'quality_audio': '🎵 Аудио (m4a)',
        'error_requires_cookies': '🔐 Видео требует вход в аккаунт. Добавьте YTDLP_COOKIES в переменные окружения, чтобы скачать.',
        'access_required': '🔒 Доступ к боту ограничен!\n\nДля получения полного доступа отправьте код приглашения:\n/code <ваш_код>\n\nПример: /code ABC123',
        'code_accepted': '✅ Код принят! Теперь у вас есть полный доступ ко всем функциям бота.',
        'code_invalid': '❌ Неверный код доступа.',
        'admin_stats': '📊 Статистика бота:',
        'admin_codes': '📝 Активные коды доступа:',
        'code_created': '✅ Создан новый код доступа: {code}',
        'code_deactivated': '✅ Код доступа деактивирован.',
        'not_admin': '❌ У вас нет прав администратора.',
    },
    'en': {
        'hello': 'Hello! 👋 I download videos from YouTube, Instagram, TikTok and other sites.\n\nJust send me a link, choose quality — and get your video!\n\nCommands:\n/history — view download history\n/help — help\n/language — choose language',
        'help_intro': '📌 How to use:',
        'help_text': '1. Send a link (YouTube, Instagram, TikTok, etc.)\n2. Choose quality:\n   🟢 144p — smallest\n   ⚡ 240p — fast\n   📹 360p — normal\n   🎬 HD — best\n   🎵 Audio — audio only\n3. Wait for upload 📥',
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
        'quality_audio': '🎵 Audio (m4a)',
        'error_requires_cookies': '🔐 This video requires login. Add YTDLP_COOKIES env variable to download.',
        'access_required': '🔒 Bot access is restricted!\n\nTo get full access, send your invitation code:\n/code <your_code>\n\nExample: /code ABC123',
        'code_accepted': '✅ Code accepted! You now have full access to all bot features.',
        'code_invalid': '❌ Invalid access code.',
        'admin_stats': '📊 Bot statistics:',
        'admin_codes': '📝 Active access codes:',
        'code_created': '✅ New access code created: {code}',
        'code_deactivated': '✅ Access code deactivated.',
        'not_admin': '❌ You do not have admin privileges.',
    }
}


def t(user_id, key, **kwargs):
    """Get translation for user's language"""
    lang = get_user_language(user_id)
    text = TRANSLATIONS.get(lang, TRANSLATIONS['ru']).get(key, key)
    return text.format(**kwargs) if kwargs else text


def requires_auth(func):
    """Декоратор для проверки авторизации пользователя"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        
        # Админы всегда имеют доступ
        if user_id in ADMIN_IDS:
            return await func(update, context, *args, **kwargs)
        
        if not is_user_authorized(user_id):
            await update.message.reply_text(t(user_id, 'access_required'))
            return
        
        # Логируем запрос
        log_user_request(user_id, update.message.text if update.message else 'callback')
        
        return await func(update, context, *args, **kwargs)
    return wrapper


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
    
    # Если пользователь уже авторизован, показываем приветствие
    if is_user_authorized(user.id) or user.id in ADMIN_IDS:
        msg = t(user.id, 'hello')
        await update.message.reply_text(msg)
    else:
        # Показываем сообщение о необходимости кода
        msg = t(user.id, 'access_required')
        await update.message.reply_text(msg)


@requires_auth
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
    # Эта команда доступна всем (даже неавторизованным)
    keyboard = [
        [InlineKeyboardButton('Русский', callback_data=f'lang_ru_{user.id}')],
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


@requires_auth
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
        suffix = 'p' if quality_str and quality_str.isdigit() else ''
        lines.append(f'[{rid}] {status.upper()} | {quality_str}{suffix}\n{short_url}\n{ts[:10]}\n')
    text = '\n'.join(lines[:15])
    await update.message.reply_text(f'{t(user.id, "history_title")}\n\n{text}')


@requires_auth
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
        ],
        [
            InlineKeyboardButton(t(user.id, 'quality_audio'), callback_data=f'quality_audio_{rowid}')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(t(user.id, 'choose_quality'), reply_markup=reply_markup)


async def quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Проверяем авторизацию
    user_id = query.from_user.id
    if not is_user_authorized(user_id) and user_id not in ADMIN_IDS:
        await query.answer(t(user_id, 'access_required'), show_alert=True)
        return
    
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
    label = f'{quality}p' if quality != 'audio' else 'audio'
    await query.edit_message_text(f'⏳ Скачиваю {"аудио" if quality == "audio" else "видео"} ({label})...')
    asyncio.create_task(download_and_send(url, query, context, rowid, quality))


async def download_and_send(url, query, context: ContextTypes.DEFAULT_TYPE, rowid: int, quality: str):
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    
    tempdir = tempfile.mkdtemp(dir=DOWNLOADS_DIR)
    
    quality_formats = {
        '144': 'worst[height<=144][ext=mp4]/worst',
        '240': 'worst[height<=240][ext=mp4]/worst',
        '360': 'worst[height<=360][ext=mp4]/worst',
        '720': 'best[height<=720][ext=mp4]/best[ext=mp4]',
        'hd': 'best[ext=mp4]/best',
        'audio': 'bestaudio[ext=m4a]/bestaudio/best'
    }
    
    ydl_opts = {
        'format': quality_formats.get(quality, 'best[ext=mp4]'),
        'outtmpl': os.path.join(tempdir, '%(id)s.%(ext)s'),
        'noplaylist': True,
        'quiet': False,
        'no_warnings': True,
        'socket_timeout': 60,
        'http_chunk_size': 1024 * 1024,
        'throttledratelimit': 100 * 1024,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Referer': 'https://www.youtube.com/'
        },
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
        
        with open(filepath, 'rb') as media_file:
            if quality == 'audio':
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=media_file,
                    caption=f'✅ {title[:60]}\n📊 {size // (1024*1024)}MB | audio'
                )
            else:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=media_file,
                    caption=f'✅ {title[:60]}\n📊 {size // (1024*1024)}MB | {quality}p'
                )
        
        update_history(rowid, 'done', os.path.basename(filepath), quality=quality)
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f'Successfully downloaded {url}')
        
    except Exception as e:
        logger.exception(f'Download failed for {url}: {e}')
        update_history(rowid, 'failed', quality=quality)
        
        error_msg = str(e).lower()
        if 'sign in to confirm' in error_msg or 'use --cookies' in error_msg or 'login required' in error_msg or ('cookie' in error_msg and 'youtube' in error_msg):
            msg = t(query.from_user.id, 'error_requires_cookies')
        elif 'timed out' in error_msg or 'timeout' in error_msg:
            msg = t(query.from_user.id, 'error_timeout')
        elif 'not available' in error_msg:
            msg = t(query.from_user.id, 'error_unavailable')
        else:
            msg = f'❌ {t(query.from_user.id, "error_general", error=str(e)[:80])}'
        
        await context.bot.send_message(chat_id=chat_id, text=msg)
        
    finally:
        try:
            shutil.rmtree(tempdir)
        except Exception as e:
            logger.warning(f'Failed to clean temp dir: {e}')


async def code_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /code для ввода кода доступа"""
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
        
        # Отправляем приветственное сообщение после авторизации
        msg = t(user_id, 'hello')
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text(t(user_id, 'code_invalid'))


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для просмотра статистики (только для админов)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(t(user_id, 'not_admin'))
        return
    
    stats = get_user_stats()
    
    stats_text = f"""{t(user_id, 'admin_stats')}

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
    """Создание нового кода доступа (только для админов)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(t(user_id, 'not_admin'))
        return
    
    # Генерируем код или используем переданный
    code = context.args[0].upper() if context.args else None
    new_code = create_access_code(code)
    
    await update.message.reply_text(t(user_id, 'code_created', code=new_code))


async def list_codes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список всех кодов доступа (только для админов)"""
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
    """Деактивация кода доступа (только для админов)"""
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


def main():
    init_db()
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        print('❌ Please set TELEGRAM_TOKEN environment variable')
        return
    
    # Проверяем, есть ли уже коды доступа, если нет - создаем первый
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM access_codes')
    code_count = cur.fetchone()[0]
    conn.close()
    
    if code_count == 0:
        if ADMIN_IDS:
            # Если есть админы, создаем код для них
            default_code = create_access_code('ADMIN2026')
            logger.info(f'📝 Admin access code created: {default_code}')
            print(f'📝 Admin access code: {default_code}')
            print(f'📝 Use /create_code YOURCODE to create more codes')
        else:
            # Если нет админов, создаем код по умолчанию
            default_code = create_access_code('WELCOME123')
            logger.info(f'📝 Default access code created: {default_code}')
            print(f'📝 Default access code: {default_code}')
            print(f'⚠️ Set ADMIN_IDS to your Telegram user ID for admin access')
    
    app = ApplicationBuilder().token(token).build()
    
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
    
    port = int(os.getenv('PORT', '8443'))
    if WEBHOOK_URL:
        logger.info(f'🤖 Starting webhook mode on port {port} with URL {WEBHOOK_URL}')
        app.run_webhook(listen='0.0.0.0', port=port, webhook_url=WEBHOOK_URL)
    else:
        logger.info('🤖 Starting polling mode')
        app.run_polling()


if __name__ == '__main__':
    main()