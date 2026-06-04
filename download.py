import os
import logging
import tempfile
import shutil
import asyncio
import time
import random
from yt_dlp import YoutubeDL
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import DOWNLOADS_DIR, YTDLP_COOKIES, YTDLP_PROXY
from database import update_history
from translations import t

logger = logging.getLogger(__name__)

# Расширенный список User-Agents для обхода блокировок
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15',
]

# Оптимизированные форматы для разных платформ
QUALITY_FORMATS = {
    '144': 'worst[height<=144]/worst',
    '240': 'worst[height<=240]/worst',
    '360': 'best[height<=360]/worst[height<=360]',
    '720': 'best[height<=720]/best[height<=720]',
    'hd': 'best[vcodec!=none][acodec!=none]/best',
    'audio': 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best'
}

# Fallback форматы если основной не работает
QUALITY_FORMATS_FALLBACK = {
    '144': 'worst',
    '240': 'worst',
    '360': 'best[height<=480]/best',
    '720': 'best',
    'hd': 'best',
    'audio': 'bestaudio'
}


def get_video_url_from_info(info):
    """
    Извлекает прямую ссылку на видео из информации yt-dlp.
    Возвращает URL видео или None.
    """
    try:
        # Сначала пытаемся получить URL напрямую
        if info.get('url'):
            return info['url']
        
        # Если нет, ищем в форматах (берём последний, обычно самый качественный)
        if info.get('formats') and isinstance(info['formats'], list):
            for fmt in reversed(info['formats']):
                if fmt.get('url'):
                    return fmt['url']
        
        # Пытаемся через requester_http
        if info.get('http_headers'):
            return None
            
        return None
    except Exception as e:
        logger.warning(f'Ошибка при извлечении URL: {e}')
        return None


def get_ydl_options(quality, tempdir, use_cookies=True, user_agent_idx=0, use_fallback=False, method=0):
    """
    Генерирует оптимизированные опции yt-dlp с обходом блокировок.
    method: 0-стандартный, 1-без post-процессинга, 2-минимальный, 3-aggressive
    """
    # Выбираем качество формата
    format_str = QUALITY_FORMATS_FALLBACK.get(quality) if use_fallback else QUALITY_FORMATS.get(quality, 'best')
    
    # Выбираем User-Agent
    user_agent = USER_AGENTS[user_agent_idx % len(USER_AGENTS)]
    
    # Базовые опции
    ydl_opts = {
        'format': format_str,
        'outtmpl': os.path.join(tempdir, '%(id)s.%(ext)s'),
        'quiet': False,
        'no_warnings': False,
        'noplaylist': True,
        'socket_timeout': 60,
        'http_chunk_size': 1024 * 1024 * 2,
        'retries': 5,
        'fragment_retries': 5,
        'skip_unavailable_fragments': True,
        
        # User-Agent и Headers
        'user_agent': user_agent,
        'headers': {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Referer': 'https://www.youtube.com/',
            'DNT': '1',
            'Cache-Control': 'max-age=0',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
        },
        
        # Rate limiting обход
        'sleep_interval': random.uniform(0.5, 1.5),
        'max_sleep_interval': 3,
        'rate_limit': 100 * 1024,
        
        'socket_timeout': 60,
        'default_search': 'auto',
        'extract_flat': False,
    }
    
    # Применяем разные методы (вариации)
    if method == 1:
        # Без постпроцессинга
        ydl_opts['postprocessors'] = []
        ydl_opts['prefer_ffmpeg'] = False
    elif method == 2:
        # Минимальный - отключаем как можно больше
        ydl_opts['no_color'] = True
        ydl_opts['no_progress'] = True
        ydl_opts['quiet'] = True
        ydl_opts['extract_flat'] = True
    elif method == 3:
        # Aggressive - увеличиваем retries и timeouts
        ydl_opts['retries'] = 10
        ydl_opts['fragment_retries'] = 10
        ydl_opts['socket_timeout'] = 90
        ydl_opts['http_chunk_size'] = 1024 * 1024
    
    # Proxy если указан
    if YTDLP_PROXY:
        ydl_opts['proxy'] = YTDLP_PROXY
    
    # Удаляем None значения
    ydl_opts = {k: v for k, v in ydl_opts.items() if v is not None}
    
    # Добавляем cookies если есть
    if use_cookies and YTDLP_COOKIES:
        cookies_path = os.path.join(tempdir, 'cookies.txt')
        try:
            with open(cookies_path, 'w', encoding='utf-8') as f:
                f.write(YTDLP_COOKIES)
            ydl_opts['cookiefile'] = cookies_path
            logger.info('✅ Cookies загружены из переменной окружения')
        except Exception as e:
            logger.warning(f'⚠️ Ошибка при загрузке cookies: {e}')
    
    return ydl_opts


async def download_and_send(url, query, context: ContextTypes.DEFAULT_TYPE, rowid: int, quality: str):
    """
    Скачивает видео/аудио с множеством вариаций обхода блокировок.
    """
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    user_id = query.from_user.id
    
    tempdir = tempfile.mkdtemp(dir=DOWNLOADS_DIR)
    filepath = None
    info = None
    video_url = None
    
    try:
        logger.info(f'🔽 Начинаю скачивание: {url} (качество: {quality})')
        
        # Расширенная стратегия: 8 попыток с разными комбинациями
        attempts = [
            # (use_cookies, use_fallback, method, quality_override)
            (True, False, 0, quality),       # 1. С cookies, стандартный метод
            (False, False, 0, quality),      # 2. Без cookies, стандартный метод
            (False, False, 1, quality),      # 3. Без cookies, без постпроцессинга
            (True, True, 0, '360'),          # 4. С cookies, fallback, 360p
            (False, True, 0, '360'),         # 5. Без cookies, fallback, 360p
            (False, False, 3, quality),      # 6. Без cookies, aggressive mode
            (False, True, 1, '240'),         # 7. Без cookies, fallback, 240p, без постпроцессинга
            (False, True, 3, '720'),         # 8. Без cookies, fallback, 720p, aggressive
        ]
        
        last_error = None
        
        for attempt_num, (use_cookies, use_fallback, method, qual_override) in enumerate(attempts, 1):
            try:
                logger.info(f'📍 Попытка {attempt_num}/{len(attempts)}: cookies={use_cookies}, fallback={use_fallback}, method={method}, quality={qual_override}')
                
                # Выбираем разные User-Agents для разных попыток
                user_agent_idx = (attempt_num - 1) % len(USER_AGENTS)
                
                ydl_opts = get_ydl_options(
                    qual_override, 
                    tempdir, 
                    use_cookies=use_cookies,
                    user_agent_idx=user_agent_idx,
                    use_fallback=use_fallback,
                    method=method
                )
                
                # Увеличиваем timeout для каждой попытки
                ydl_opts['socket_timeout'] = 60 + (attempt_num * 15)
                
                # Пытаемся скачать
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    filepath = ydl.prepare_filename(info)
                
                logger.info(f'✅ Успешно скачано с попытки {attempt_num}')
                
                # Пытаемся извлечь прямую ссылку на видео для больших файлов
                video_url = get_video_url_from_info(info)
                
                break
                
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                logger.warning(f'❌ Попытка {attempt_num} не удалась: {str(e)[:150]}')
                
                # Ждём перед следующей попыткой (экспоненциальная задержка)
                if attempt_num < len(attempts):
                    wait_time = min(2 ** (attempt_num // 2), 10) + random.uniform(1, 3)
                    logger.info(f'⏳ Ждём {wait_time:.1f}с перед следующей попыткой...')
                    await asyncio.sleep(wait_time)
                
                # Если это критическая ошибка, выходим сразу
                critical_errors = ['not available', 'video not found', 'removed', 'deleted', 'private']
                if any(err in error_str for err in critical_errors):
                    logger.error(f'🚫 Критическая ошибка, выходим: {str(e)[:100]}')
                    break
        
        # Если все попытки не удались
        if not filepath or not os.path.exists(filepath):
            error_msg = str(last_error or 'Unknown error').lower()
            
            # Определяем тип ошибки и отправляем нужное сообщение
            if 'not available' in error_msg or 'video not found' in error_msg or 'removed' in error_msg or 'deleted' in error_msg:
                msg = '❌ Видео недоступно или удалено'
            elif 'private' in error_msg:
                msg = '🔒 Видео приватное'
            elif 'members only' in error_msg or 'members-only' in error_msg:
                msg = '👥 Видео доступно только для членов канала'
            elif 'timed out' in error_msg or 'timeout' in error_msg:
                msg = '⏱️ Истёк timeout при скачивании. Видео слишком большое или медленный интернет'
            elif 'sign in' in error_msg or 'login required' in error_msg or 'authorization' in error_msg:
                msg = '🔑 Требуется вход в аккаунт (попробуйте другое видео)'
            elif 'geoblocked' in error_msg or 'geo-blocked' in error_msg or 'not available in your country' in error_msg:
                msg = '🌍 Видео недоступно в вашей стране'
            elif 'too many requests' in error_msg or '429' in error_msg or 'rate limit' in error_msg:
                msg = '⚠️ Много запросов. Подождите немного и попробуйте снова'
            elif 'no suitable format' in error_msg or 'format not available' in error_msg:
                msg = '❌ Нет подходящего формата для скачивания'
            elif 'connection' in error_msg or 'network' in error_msg or 'http error' in error_msg:
                msg = '🌐 Ошибка сети. Проверьте интернет и попробуйте ещё раз'
            else:
                msg = f'❌ Ошибка скачивания: {error_msg[:80]}'
            
            logger.error(f'📛 Финальная ошибка: {last_error}')
            update_history(rowid, 'failed', quality=quality)
            
            await context.bot.send_message(chat_id=chat_id, text=msg)
            return
        
        # Проверяем размер файла
        size = os.path.getsize(filepath)
        title = info.get('title', 'Video')[:60]
        
        if size > 50 * 1024 * 1024:
            logger.warning(f'📦 Файл слишком большой: {size / (1024*1024):.1f}MB')
            
            # Создаём красивую кнопку с ссылкой вместо текста
            msg_text = f'⚠️ Файл слишком большой ({size // (1024*1024)}MB)\n\n'
            msg_text += f'📹 {title}\n\n'
            msg_text += 'Нажмите на кнопку ниже, чтобы скачать:'
            
            keyboard = []
            
            # Добавляем кнопку для прямого скачивания если есть URL
            if video_url:
                keyboard.append([InlineKeyboardButton('⬇️ Скачать видео', url=video_url)])
            
            # Альтернативные опции
            keyboard.extend([
                [InlineKeyboardButton('🎥 Качество 360p', callback_data=f'quality_360_{rowid}')],
                [InlineKeyboardButton('🎵 Только аудио', callback_data=f'quality_audio_{rowid}')]
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            update_history(rowid, 'too_large', quality=quality)
            await context.bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=reply_markup)
            return
        
        # Обновляем статус загрузки
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f'📤 Загружаю в Telegram...\n"{title}"\n{size // (1024*1024)}MB'
        )
        
        # Отправляем файл в Telegram
        with open(filepath, 'rb') as media_file:
            try:
                if quality == 'audio':
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=media_file,
                        caption=f'✅ {title}\n📊 {size // (1024*1024)}MB | аудио'
                    )
                else:
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=media_file,
                        caption=f'✅ {title}\n📊 {size // (1024*1024)}MB | {quality}p'
                    )
            except Exception as e:
                logger.error(f'❌ Ошибка при отправке в Telegram: {e}')
                error_msg = str(e).lower()
                if 'request entity too large' in error_msg or 'file too large' in error_msg:
                    msg = f'⚠️ Файл слишком большой даже для Telegram ({size // (1024*1024)}MB)\n\n'
                    msg += 'Попробуйте качество пониже или скачайте напрямую'
                else:
                    msg = f'❌ Ошибка отправки: {str(e)[:100]}'
                
                update_history(rowid, 'send_failed', quality=quality)
                await context.bot.send_message(chat_id=chat_id, text=msg)
                return
        
        # Успешно отправили
        update_history(rowid, 'done', os.path.basename(filepath), quality=quality)
        
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except:
            pass
        
        logger.info(f'✅ Успешно скачано и отправлено: {url}')
        
    except Exception as e:
        logger.exception(f'💥 Критическая ошибка: {e}')
        update_history(rowid, 'failed', quality=quality)
        
        try:
            msg = f'💥 Неожиданная ошибка: {str(e)[:100]}'
            await context.bot.send_message(chat_id=chat_id, text=msg)
        except:
            pass
        
    finally:
        # Очищаем временную директорию
        try:
            shutil.rmtree(tempdir)
            logger.info(f'🗑️ Временная директория удалена')
        except Exception as e:
            logger.warning(f'⚠️ Ошибка при удалении временной директории: {e}')
