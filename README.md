# Telegram Video Downloader Bot

Локальная версия бота, который принимает ссылку на YouTube, Instagram, TikTok и других сайтов, скачивает видео с помощью `yt-dlp` и отправляет его пользователю.

## Фичи

- ✅ Скачивание видео с YouTube, Instagram, TikTok и др.
- ✅ Выбор качества (360p, 720p, HD)
- ✅ SQLite история всех загрузок
- ✅ Обработка timeout-ошибок
- ✅ Поддержка ограничения размера файла (макс 50MB для Telegram)

## Требования

- Python 3.9+
- Установите зависимости:

```bash
pip install -r requirements.txt
```

## Переменные окружения

- `TELEGRAM_TOKEN` — токен вашего бота (получить у **BotFather** в Telegram)
- `YTDLP_COOKIES` — содержимое cookies.txt для YouTube, если видео требует вход или подтверждение
- `SUPPORT_BOT` — имя support-бота для ссылки в /help
- `WEBHOOK_URL` — полный HTTPS URL, если бот запускается в контейнере/на Railway и должен использовать webhook вместо polling

## Запуск локально

### Вариант 1: Windows PowerShell

```powershell
# Создайте виртуальное окружение (один раз)
python -m venv venv
.\venv\Scripts\Activate.ps1

# Установите зависимости (один раз)
pip install -r requirements.txt

# Запустите бота
$env:TELEGRAM_TOKEN = "ВАШ_ТОКЕН_ОТ_BOTFATHER"
python tg-bot-yt.py
```

### Вариант 2: Windows CMD

```cmd
python -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
set TELEGRAM_TOKEN=ВАШ_ТОКЕН_ОТ_BOTFATHER
python tg-bot-yt.py
```

### Вариант 3: Linux/Mac

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_TOKEN="ВАШ_ТОКЕН_ОТ_BOTFATHER"
python tg-bot-yt.py
```

## История запросов

Бот хранит историю в `history.db` (SQLite) с информацией о:

- URL источника
- Выбранном качестве
- Статусе (done/failed)
- Названии скачанного файла
- Времени загрузки

Просмотреть историю: `/history` в чате с ботом

## Деплой на Railway.app (бесплатно, 24/7)

Railway.app позволяет запустить бота на бесплатном плане (5$ в месяц credits).

### Шаг 1: Подготовка к деплою

1. Убедитесь, что все файлы готовы:
   - `tg-bot-yt.py`
   - `requirements.txt`
   - `Procfile`
   - `runtime.txt`
   - `.gitignore`

### Шаг 2: Git инициализация

```bash
git init
git add .
git commit -m "Initial commit"
```

### Шаг 3: Railway

1. Зайдите на https://railway.app
2. Нажмите **"New Project"** → **"Deploy from GitHub repo"** (или загрузите напрямую)
3. Выберите репо или загрузите файлы
4. Railway автоматически обнаружит `Procfile`
5. Добавьте переменные окружения:
   - Зайдите в **Variables** (⚙️)
   - Добавьте `TELEGRAM_TOKEN = ВАШ_ТОКЕН`
   - (опционально) добавьте `SUPPORT_BOT = support_bot_username`
   - (если нужны заблокированные видео) добавьте `YTDLP_COOKIES = <содержимое cookies.txt>`
6. Нажмите **Deploy** — бот запустится!

### Альтернатива: Render.com

1. https://render.com/register
2. New → **Web Service**
3. Подключите GitHub или загрузите
4. Environment: `Python 3.11`
5. Build command: `pip install -r requirements.txt`
6. Start command: `python tg-bot-yt.py`
7. Add env var: `TELEGRAM_TOKEN = ВАШ_ТОКЕН`
8. Деплой!

### Альтернатива: Heroku (платно, но можно бесплатный trial)

Heroku больше не предоставляет бесплатный tier, но вы можете использовать credits.

## Команды бота

- `/start` — справка
- `/help` — как пользоваться
- `/history` — просмотреть историю загрузок

## Решение ошибок

### Ошибка "Timed out"

- Попробуйте 360p вместо HD
- Возможно, видео слишком большое или соединение медленное

### Ошибка "Видео недоступно"

- Видео может быть приватным, удалённым или по геоблоку

### Лимит 50MB

- Telegram имеет лимит на размер файлов
- Используйте 360p для больших видео

## Структура папок

```
WithGemeni/
├── tg-bot-yt.py      # Основной скрипт бота
├── requirements.txt    # Зависимости
├── Procfile           # Для деплоя (Railway/Heroku)
├── runtime.txt        # Версия Python
├── .gitignore         # Исключения для git
├── README.md          # Этот файл
├── history.db         # БД истории (создаётся автоматически)
└── downloads/         # Временная папка скачиваний (создаётся автоматически)
```

## TODO / Идеи для развития

- [ ] Поддержка аудио-только (MP3 с YouTube)
- [ ] Ограничение размера по выбору
- [ ] Поддержка плейлистов
- [ ] Веб-интерфейс для управления
- [ ] Кэширование часто скачиваемых видео

## Лицензия

MIT

---

**Автор:** GitHub Copilot | **Дата:** 2026
