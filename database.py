import sqlite3
from datetime import datetime
from config import DB_PATH


def init_db():
    """Initialize database tables"""
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
    """Get user's language preference"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT language FROM user_settings WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 'ru'


def set_user_language(user_id, lang):
    """Set user's language preference"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('INSERT OR REPLACE INTO user_settings (user_id, language) VALUES (?, ?)', (user_id, lang))
    conn.commit()
    conn.close()


def is_user_authorized(user_id):
    """Check if user is authorized"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT is_authorized FROM user_settings WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] == 1 if row else False


def authorize_user(user_id, username=None):
    """Authorize a user"""
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
    """Log a user request"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute('INSERT INTO user_requests (user_id, command, ts) VALUES (?, ?, ?)', (user_id, command, now))
    cur.execute('UPDATE user_settings SET last_active = ?, request_count = request_count + 1 WHERE user_id = ?', (now, user_id))
    conn.commit()
    conn.close()


def create_access_code(code=None):
    """Create an access code"""
    import secrets
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
    """Validate an access code"""
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
    """Get all access codes"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT code, created_at, used_by, is_active FROM access_codes ORDER BY created_at DESC')
    rows = cur.fetchall()
    conn.close()
    return rows


def deactivate_access_code(code):
    """Deactivate an access code"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('UPDATE access_codes SET is_active = 0 WHERE code = ?', (code,))
    conn.commit()
    conn.close()


def get_user_stats():
    """Get user statistics"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute('SELECT COUNT(*) FROM user_settings WHERE is_authorized = 1')
    total_users = cur.fetchone()[0]
    
    cur.execute('SELECT COUNT(*) FROM user_settings')
    total_registered = cur.fetchone()[0]
    
    today = datetime.utcnow().date().isoformat()
    cur.execute('SELECT COUNT(DISTINCT user_id) FROM user_requests WHERE ts LIKE ?', (f'{today}%',))
    active_today = cur.fetchone()[0]
    
    cur.execute('''SELECT user_id, username, request_count, last_active 
                   FROM user_settings 
                   WHERE is_authorized = 1 
                   ORDER BY request_count DESC LIMIT 10''')
    top_users = cur.fetchall()
    
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


def add_history(user_id, username, url, status='pending', filename=None, quality=None):
    """Add download to history"""
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
    """Update download history"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('UPDATE history SET status = ?, filename = ?, quality = ? WHERE id = ?', (status, filename, quality, rowid))
    conn.commit()
    conn.close()


def get_history_for_user(user_id, limit=20):
    """Get download history for user"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT id, url, ts, status, filename, quality FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?', (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows
