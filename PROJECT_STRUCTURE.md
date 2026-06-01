# Project Structure

Бот разбит на модули для улучшения читаемости и поддерживаемости:

## 📁 Файлы

### `tg-bot-yt.py`

**Главный entry point** — запускает бота, регистрирует handlers, инициализирует БД.

### `config.py`

**Конфигурация** — переменные окружения, пути, константы:

- `TELEGRAM_TOKEN` — токен бота
- `ADMIN_IDS` — ID администраторов
- `YTDLP_COOKIES`, `YTDLP_PROXY` — параметры yt-dlp
- `WEBHOOK_URL` — URL для webhook (если используется)

### `database.py`

**Работа с БД** (SQLite):

- Инициализация таблиц (`init_db`)
- Управление пользователями (`authorize_user`, `is_user_authorized`)
- Языки пользователей (`get_user_language`, `set_user_language`)
- Коды доступа (`create_access_code`, `validate_access_code`)
- История загрузок (`add_history`, `update_history`, `get_history_for_user`)
- Статистика (`get_user_stats`)

### `translations.py`

**Многоязычность** (русский, английский, украинский):

- `TRANSLATIONS` — словарь переводов
- `t(user_id, key, **kwargs)` — функция получения перевода

### `decorators.py`

**Декораторы**:

- `@requires_auth` — проверка авторизации пользователя

### `utils.py`

**Утилиты**:

- `is_url(text)` — проверка наличия URL в тексте
- `truncate_text(text, length)` — обрезание текста
- `format_duration(seconds)` — форматирование времени

### `download.py` ⭐ **УЛУЧШЕНО**

**Логика скачивания видео/аудио**:

- `get_ydl_options()` — генерирует опции yt-dlp **с header spoofing**
- `download_and_send()` — основная функция скачивания
- **Новое**: User-Agent rotation для обхода YouTube rate limiting
- **Новое**: Автоматический retry с другими заголовками при ошибках 429/auth

### `handlers.py`

**Обработчики команд и callback'и**:

- `/start`, `/help`, `/history`, `/language` — основные команды
- `/code <code>` — ввод кода доступа
- `/stats` — статистика (admin)
- `/create_code`, `/list_codes`, `/deactivate_code` — управление кодами (admin)
- Callback'и для выбора качества и языка

## 🔧 Что изменилось

### ✨ Улучшения в `download.py`

1. **Header Spoofing** — добавлены реальные User-Agent и Referer headers для обхода YouTube rate limiting:

   ```python
   USER_AGENTS = [
       'Mozilla/5.0 (Windows NT 10.0; Win64; x64)...',
       'Mozilla/5.0 (Macintosh; Intel Mac OS X)...',
   ]
   ```

2. **Автоматический Retry** — при ошибке 429 или auth error:
   - Повторная попытка с другим User-Agent
   - Удаление cookies для избежания конфликтов
   - Sleep interval между запросами

3. **Лучшая обработка ошибок** — различные сообщения для разных типов ошибок

## 📊 Структура БД

```
history.db
├── history (загрузки)
├── user_settings (язык, авторизация, статистика)
├── access_codes (коды доступа)
└── user_requests (логи команд)
```

## 🚀 Развертывание

### Локально:

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или .\venv\Scripts\Activate.ps1  # Windows
pip install -r requirements.txt
export TELEGRAM_TOKEN="your_token"
export ADMIN_IDS="your_id"
python tg-bot-yt.py
```

### Railway:

Все файлы (включая модули) автоматически загружаются. Railway запустит `Procfile`:

```
worker: python tg-bot-yt.py
```

## 📝 Логирование

Структурированное логирование на разных уровнях (INFO, WARNING, ERROR).

Переменная окружения: `LOGLEVEL` (default: `INFO`)

## ❓ FAQ

**Q: Почему модули?**
A: Легче найти нужное, модифицировать, тестировать отдельные части.

**Q: Где мои данные?**
A: В `history.db` (SQLite), создается автоматически.

**Q: Как добавить функцию?**
A: Отредактируйте нужный модуль (например, `handlers.py` для новой команды).
