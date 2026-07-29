# Design Spec: Веб-сервис анализа культурно-исторических объектов

Дата: 2026-07-29

## 1. Цель

Разработать веб-сервис для сбора и анализа отзывов о культурно-исторических объектах из открытых источников (блоги, форумы, соцсети, путеводители) с использованием локальной нейросети (Llama 3.1-8B через LM Studio). Пользователь задаёт название объекта, ключевые слова и годовую посещаемость — сервис ищет упоминания, определяет наличие ключевых слов, извлекает даты и геопривязку автора, выводит статистику.

## 2. Архитектура

```
Frontend (HTML/Jinja2)  ←→  FastAPI (Python)
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
               SearXNG      LM Studio    SQLite
            (Yandex+Google) (Llama 3.1)
```

### 2.1. Компоненты

| Компонент | Роль | Технология |
|-----------|------|-----------|
| **Frontend** | Форма ввода, страница прогресса, страница отчёта | Jinja2-шаблоны + простой JS (SSE для прогресса) |
| **Backend** | API, оркестрация поиска и анализа | Python FastAPI + aiohttp + BackgroundTasks |
| **Search Module** | Поиск URL по ключевым словам через мета-поисковик | Запросы к SearXNG JSON API |
| **Text Parser** | Выкачка содержимого страниц, передача в LLM | aiohttp + HTTP-запросы к LM Studio |
| **LLM** | Анализ текста: релевантность, ключевые слова, даты, геопривязка | Llama 3.1-8B (OpenAI-совместимый API LM Studio) |
| **База данных** | Хранение истории запросов и результатов | SQLite (через SQLAlchemy) |
| **Report Generator** | Расчёт статистики, формирование отчёта | Python (встроенный модуль) |
| **SearXNG** | Мета-поиск: агрегация Google + Yandex | Отдельный сервис (docker) |

### 2.2. Локальная нейросеть

- **Модель:** Meta-Llama-3.1-8B-Instruct-GGUF (квантованая)
- **Среда:** LM Studio с OpenAI-совместимым API на localhost
- **Эндпоинт:** `POST /v1/chat/completions`
- **Промпт:** JSON-схема ответа (см. п. 4)

## 3. Поток выполнения

```
1. Пользователь заполняет форму:
   - Название объекта (обязательно)
   - Ключевые слова (обязательно)
   - Годовая посещаемость (число)
   - Ссылки для обязательной проверки (опционально, список URL)
   → [Запустить анализ]

2. FastAPI создаёт задачу в БД (status=processing) и запускает
   фоновый процесс через BackgroundTasks.

3. Фоновый процесс:
   A. Для каждого ключевого слова формирует запросы:
      "<объект>", "<объект> <ключевое_слово1>", "<объект> <ключевое_слово2>", ...
   B. Отправляет запросы в SearXNG (JSON API)
   C. Получает список URL + сниппеты
   D. Добавляет в очередь URL, введённые пользователем вручную
   E. Для каждого URL:
      i.   Скачивает HTML (aiohttp)
      ii.  Извлекает текст (BeautifulSoup)
      iii. Отправляет в Llama 3.1 на анализ
      iv.  Сохраняет результат в БД
      v.   Публикует событие прогресса (SSE): { status, url, title,
            processed, total, found_keyword }

4. После обработки всех URL:
   - Обновляет статус задачи (status=completed)
   - Генерирует финальный отчёт

5. Клиент получает финальный отчёт (перенаправление на страницу
   результата или SSE-событие "done").
```

## 4. LLM-промпт

Запрос к Llama 3.1 для каждого URL:

```
Ты — анализатор текстов. Определи по тексту ниже, упоминается ли
заданный объект, есть ли ключевое слово, дата и геопривязка автора.

Объект: {object_name}
Ключевое слово: {keyword}

Текст: {title}
{text}

Ответь строго в формате JSON без пояснений:
{
  "mentions_object": true/false,
  "object_name": "название из текста или null",
  "has_keyword": true/false,
  "keyword_found": "найденное ключевое слово или null",
  "date_mentioned": "дата (ДД.ММ.ГГГГ) из текста или null",
  "publication_date": "дата публикации страницы или null",
  "author_location": "геопривязка автора (город, страна, регион) или null",
  "relevance_score": 0.0-1.0
}
```

Конфигурация LLM: temperature=0.1, max_tokens=256 (для скорости и детерминированности).

## 5. Поля формы ввода

| Поле | Тип | Обязательное | Описание |
|------|-----|-------------|----------|
| object_name | text | да | Название культурно-исторического объекта |
| keywords | text | да | Ключевые слова через запятую |
| annual_visitors | number | нет | Годовая посещаемость объекта |
| manual_urls | textarea | нет | Ссылки для обязательной проверки (по одной на строку) |

## 6. Отчёт (страница результатов)

После завершения анализа пользователь видит:

- **Статус:** "Готово" / "Ошибка"
- **Объект:** (название)
- **Ключевые слова:** (список)
- **Всего найдено упоминаний объекта:** N
- **Упоминаний с ключевым словом:** M (X%)
- **Посещаемость в год:** (из формы)
- **% от посетителей:** (M / annual_visitors × 100) — если указана
- **Таблица результатов:**

  | # | URL | Заголовок | Ключевое слово | Дата публикации | Геопривязка автора | Релевантность |
  |---|-----|-----------|---------------|----------------|-------------------|--------------|
  | 1 | ... | ...       | Византия     | 12.05.2024    | Екатеринбург     | 0.95         |

## 7. База данных (SQLite)

```sql
-- Таблица задач
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,           -- UUID
    object_name TEXT NOT NULL,
    keywords TEXT NOT NULL,
    annual_visitors INTEGER,
    manual_urls TEXT,               -- JSON-список
    status TEXT DEFAULT 'pending',  -- pending, processing, completed, error
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- Таблица результатов
CREATE TABLE results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    url TEXT NOT NULL,
    title TEXT,
    mentions_object BOOLEAN,
    has_keyword BOOLEAN,
    keyword_found TEXT,
    date_mentioned TEXT,
    publication_date TEXT,
    author_location TEXT,
    relevance_score REAL,
    raw_text_hash TEXT,              -- для дедупликации
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 8. SSE-протокол прогресса

Эндпоинт: `GET /api/tasks/{task_id}/progress`

```
event: progress
data: {"processed": 3, "total": 15, "found_keyword": 1,
       "current_url": "https://...", "current_title": "..."}

event: progress
data: {"processed": 4, "total": 15, ...}  -- после каждого URL

event: done
data: {"task_id": "...", "redirect": "/results/..."}
```

## 9. API-эндпоинты

| Метод | Путь | Описание |
|-------|------|---------|
| GET | / | Главная страница с формой |
| POST | /api/search | Создать задачу анализа |
| GET | /api/tasks/{task_id}/progress | SSE-поток прогресса |
| GET | /api/tasks/{task_id}/results | JSON с результатами (для SPA) |
| GET | /results/{task_id} | Страница отчёта |

На будущее (в проекте, но не в MVP):

| Метод | Путь | Описание |
|-------|------|---------|
| POST | /api/auth/login | Аутентификация |
| GET | /api/tasks/history | История запросов пользователя |

## 10. Кэширование и дедупликация

- Хранить хеш содержимого страницы (raw_text_hash) для пропуска дубликатов
- Если URL уже обработан ранее — взять результат из url_cache:

```sql
CREATE TABLE url_cache (
    url TEXT PRIMARY KEY,
    object_name TEXT,
    result_json TEXT,        -- полный JSON-ответ LLM
    raw_text_hash TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 11. Обработка ошибок

- SearXNG недоступен → вернуть сообщение и предложить ручные URL
- Страница не загружается (таймаут/403/404) → пропустить, записать ошибку
- Llama 3.1 не отвечает → повторить 2 раза, затем пропустить
- Невалидный JSON в ответе LLM → повторный запрос (max_retries=2)

## 12. План дальнейшего развития (post-MVP)

- Аутентификация и многопользовательский режим
- Экспорт отчёта в PDF/XLSX
- Периодический мониторинг объектов (запланированные задачи)
- Расширение поисковых engines в SearXNG (Bing, Baidu)
- Визуализация (графики распределения по годам, карта геопривязок)
