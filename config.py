import os
import re

# Environment variables
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip().isdigit()]
YTDLP_COOKIES = os.getenv('YTDLP_COOKIES')
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
