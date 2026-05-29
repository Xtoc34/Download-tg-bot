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
    conn.commit()
    conn.close()


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
    msg = '''Привет! 👋 Я скачиваю видео с YouTube, Instagram, TikTok и других сайтов.

Просто отправьте мне ссылку, выберите качество — и получите видео!

Команды:
/history — просмотреть историю загрузок
/help — справка
'''
    await update.message.reply_text(msg)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    support = os.getenv('SUPPORT_BOT')
    support_line = ''
    if support:
        # support can be username with or without @
        s = support if support.startswith('@') else f'@{support}'
        support_line = f"\nПоддержка / Support: {s}"

    msg = f'''📌 Как пользоваться:
1. Отправьте ссылку (YouTube, Instagram, TikTok, etc.)
2. Выберите качество:
   ⚡ 360p — самое быстрое, низкое качество
   📹 720p — оптимально, среднее качество
   🎬 HD — максимальное качество (может быть медленнее)
3. Ждите загрузки 📥

⚠️ Лимит Telegram: макс 50MB за раз{support_line}
'''
    await update.message.reply_text(msg)


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    rows = get_history_for_user(user.id)
    if not rows:
        await update.message.reply_text('История пустая.')
        return
    lines = []
    for r in rows:
        rid, url, ts, status, filename, quality = r
        short_url = url[:40] + '...' if len(url) > 40 else url
        quality_str = quality if quality else '-'
        lines.append(f'[{rid}] {status.upper()} | {quality_str}p\n{short_url}\n{ts[:10]}\n')
    text = '\n'.join(lines[:15])
    await update.message.reply_text(f'📋 Ваша история (последние 15):\n\n{text}')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not is_url(text):
        await update.message.reply_text('❌ Пожалуйста, пришлите ссылку (YouTube, Instagram, TikTok и др.).')
        return
    
    user = update.effective_user
    rowid = add_history(user.id, user.username or '', text)
    
    keyboard = [
        [
            InlineKeyboardButton("⚡ 360p (быстро)", callback_data=f'quality_360_{rowid}'),
            InlineKeyboardButton("📹 720p (обычно)", callback_data=f'quality_720_{rowid}'),
        ],
        [
            InlineKeyboardButton("🎬 HD (лучше, медленнее)", callback_data=f'quality_hd_{rowid}'),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите качество:', reply_markup=reply_markup)


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
        '360': 'worst[ext=mp4]/worst',
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
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f'⚠️ Файл {size // (1024*1024)}MB слишком большой (лимит 50MB). Попробуйте 360p.'
            )
            update_history(rowid, 'failed', quality=quality)
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
    app.add_handler(CommandHandler('history', history_cmd))
    app.add_handler(CallbackQueryHandler(quality_callback, pattern=r'quality_'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info('🤖 Bot started successfully!')
    app.run_polling()


if __name__ == '__main__':
    main()

