import re
from config import URL_RE


def is_url(text: str) -> bool:
    """Check if text contains a URL"""
    return bool(URL_RE.search(text))


def format_duration(seconds):
    """Format seconds into HH:MM:SS"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def truncate_text(text, length=50):
    """Truncate text to specified length"""
    return text[:length] + '...' if len(text) > length else text
