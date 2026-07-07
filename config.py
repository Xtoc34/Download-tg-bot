import os
import re

# Environment variables
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip().isdigit()]

# Cookies - сначала проверяем файл, потом переменную окружения
YTDLP_COOKIES = None
COOKIES_FILE = 'cookies_youtube.txt'

# Если есть файл cookies - используем его
if os.path.exists(COOKIES_FILE):
    try:
        with open(COOKIES_FILE, 'r', encoding='utf-8') as f:
            YTDLP_COOKIES = f.read()
        print(f'✅ Cookies загружены из файла: {COOKIES_FILE}')
    except Exception as e:
        print(f'⚠️ Ошибка при чтении файла cookies: {e}')

# Если нет файла - проверяем переменную окружения
if not YTDLP_COOKIES:
    YTDLP_COOKIES = os.getenv('YTDLP_COOKIES')
    if YTDLP_COOKIES:
        print('✅ Cookies загружены из переменной окружения: YTDLP_COOKIES')

YTDLP_PROXY = os.getenv('YTDLP_PROXY')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
SUPPORT_BOT = os.getenv('SUPPORT_BOT')
LOGLEVEL = os.getenv('LOGLEVEL', 'INFO')
PORT = int(os.getenv('PORT', '8443'))

# Paths
DB_PATH = 'history.db'
DOWNLOADS_DIR = 'downloads'
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Patterns
URL_RE = re.compile(r'https?://\S+')
