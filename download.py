import os
import logging
import tempfile
import shutil
import asyncio
from yt_dlp import YoutubeDL
from telegram.ext import ContextTypes
from config import DOWNLOADS_DIR, YTDLP_COOKIES, YTDLP_PROXY
from database import update_history
from translations import t

logger = logging.getLogger(__name__)

# Common user agents to rotate and bypass rate limiting
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

# Quality format mappings
QUALITY_FORMATS = {
    '144': 'worst[height<=144][ext=mp4]/worst',
    '240': 'worst[height<=240][ext=mp4]/worst',
    '360': 'worst[height<=360][ext=mp4]/worst',
    '720': 'best[height<=720][ext=mp4]/best[ext=mp4]',
    'hd': 'best[ext=mp4]/best',
    'audio': 'bestaudio[ext=m4a]/bestaudio/best'
}


def get_ydl_options(quality, tempdir, use_cookies=True, user_agent_idx=0):
    """
    Get yt-dlp options with header spoofing and rate limit bypass
    """
    ydl_opts = {
        'format': QUALITY_FORMATS.get(quality, 'best[ext=mp4]'),
        'outtmpl': os.path.join(tempdir, '%(id)s.%(ext)s'),
        'noplaylist': True,
        'quiet': False,
        'socket_timeout': 60,
        'http_chunk_size': 1024 * 1024,
        'throttledratelimit': 100 * 1024,
        # Bypass rate limiting
        'user_agent': USER_AGENTS[user_agent_idx % len(USER_AGENTS)],
        'headers': {
            'Referer': 'https://www.youtube.com',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
        },
        'sleep_interval': 1,  # Sleep 1 sec between requests
        'max_sleep_interval': 3,
    }

    if use_cookies and YTDLP_COOKIES:
        cookies_path = os.path.join(tempdir, 'cookies.txt')
        try:
            with open(cookies_path, 'w', encoding='utf-8') as cookie_file:
                cookie_file.write(YTDLP_COOKIES)
            ydl_opts['cookiefile'] = cookies_path
            logger.info('Using cookies from YTDLP_COOKIES')
        except Exception as e:
            logger.warning(f'Failed to write cookies file: {e}')

    if YTDLP_PROXY:
        ydl_opts['proxy'] = YTDLP_PROXY
        logger.info('Using proxy from YTDLP_PROXY')
    
    return ydl_opts


async def download_and_send(url, query, context: ContextTypes.DEFAULT_TYPE, rowid: int, quality: str):
    """
    Download video/audio and send to Telegram with improved error handling
    """
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    
    tempdir = tempfile.mkdtemp(dir=DOWNLOADS_DIR)
    
    try:
        logger.info(f'Downloading {url} with quality {quality}')
        
        # First attempt with cookies (if available)
        ydl_opts = get_ydl_options(quality, tempdir, use_cookies=True, user_agent_idx=0)
        
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
        
        except Exception as e:
            error_msg = str(e).lower()
            
            # Detect if it's a cookie/auth-related error
            cookie_error = (
                'sign in to confirm' in error_msg
                or 'use --cookies' in error_msg
                or 'login required' in error_msg
                or 'this video is available only to signed-in users' in error_msg
                or 'authorization required' in error_msg
            )
            
            logger.warning(f'First attempt failed: {str(e)[:100]}')
            
            # If it's a rate limit or auth error, retry with different user agent and no cookies
            if 'too many requests' in error_msg or '429' in error_msg or cookie_error:
                logger.info('Retrying with different user agent and headers to bypass rate limiting')
                
                fallback_opts = get_ydl_options('360', tempdir, use_cookies=False, user_agent_idx=1)
                
                try:
                    with YoutubeDL(fallback_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        filepath = ydl.prepare_filename(info)
                    logger.info('Retry succeeded with fallback options')
                except Exception as fallback_e:
                    logger.error(f'Retry also failed: {str(fallback_e)[:100]}')
                    raise  # Re-raise the fallback exception if retry fails
            else:
                raise  # Re-raise original exception if not rate limit/auth error
        
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
        
        # Check file size
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
        
        # Update message before sending
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f'📤 Загружаю "{title[:30]}"... ({size // (1024*1024)}MB)'
        )
        
        # Send to Telegram
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
        logger.info(f'Successfully downloaded and sent {url}')
        
    except Exception as e:
        logger.exception(f'Download failed for {url}: {e}')
        update_history(rowid, 'failed', quality=quality)
        
        error_msg = str(e).lower()
        
        # Determine error type and send appropriate message
        if 'timed out' in error_msg or 'timeout' in error_msg:
            msg = t(query.from_user.id, 'error_timeout')
        elif 'not available' in error_msg or 'video not found' in error_msg:
            msg = t(query.from_user.id, 'error_unavailable')
        elif ('sign in to confirm' in error_msg or 'use --cookies' in error_msg 
              or 'login required' in error_msg or 'authorization required' in error_msg):
            msg = t(query.from_user.id, 'error_requires_cookies')
        else:
            msg = f'❌ {t(query.from_user.id, "error_general", error=str(e)[:80])}'

        await context.bot.send_message(chat_id=chat_id, text=msg)
        
    finally:
        try:
            shutil.rmtree(tempdir)
        except Exception as e:
            logger.warning(f'Failed to clean temp dir: {e}')
