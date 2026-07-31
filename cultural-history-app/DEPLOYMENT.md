# Чеклист переноса на целевую машину

Целевая машина: Windows/Mac + Docker Desktop + LM Studio на хосте.

## 1. Перенос репозитория

- [ ] Скопировать репозиторий `ByzantiumSearch` на целевую машину
  - Без `cultural-history-app/venv/` (создаётся заново, только для host-режима)
  - Без `cultural-history-app/data/` (создастся при первом запуске)
- [ ] Убедиться, что внутри есть `cultural-history-app/docker-compose.yml`, `Dockerfile`, `.env.example`

## 2. Установка Docker Desktop

- [ ] Установить Docker Desktop (Windows/Mac)
- [ ] Запустить Docker Desktop, дождаться статуса "Engine running"
- [ ] Проверка: `docker --version` и `docker compose version` отвечают

## 3. Установка и настройка LM Studio

- [ ] Установить LM Studio
- [ ] Скачать модель **meta-llama-3.1-8b-instruct** (вкладка Discover/Search в LM Studio)
- [ ] Загрузить модель (локально, в чате)
- [ ] Запустить локальный сервер: вкладка **Local Server** → **Start server** (порт по умолчанию 1234)
- [ ] Проверка в браузере: `http://localhost:1234/v1/models` должен вернуть JSON со списком моделей

## 4. Запуск приложения (Docker-режим, основной)

- [ ] Открыть терминал в `cultural-history-app/`
- [ ] `docker compose up -d --build`
- [ ] Дождаться готовности (первый запуск качает образы SearXNG и собирает приложение)
- [ ] Открыть `http://localhost:8000` в браузере
- [ ] Проверка: страница поиска загружается
- [ ] Проверка: SearXNG отвечает на `http://localhost:8888`

## 5. Сквозная проверка

- [ ] Ввести название культурно-исторического объекта + ключевые слова
- [ ] Запустить анализ, дождаться прогресса по SSE
- [ ] Отчёт сформирован, статистика корректна
- [ ] Перезапустить контейнер: `docker compose restart app` — данные в БД сохранились (volume `./data`)

## Полезные команды

```powershell
# Остановить всё
docker compose down

# Пересобрать после изменения Python-кода
docker compose up -d --build

# Логи приложения
docker compose logs -f app
```

## Если что-то не работает

| Симптом | Причина | Решение |
|---|---|---|
| Приложение стартует, но нет результатов поиска | Контейнер не достаёт до LM Studio | Проверить, что Local Server в LM Studio запущен и `http://localhost:1234/v1/models` отвечает на хосте |
| `http://localhost:1234/v1/models` отвечает на хосте, но не в контейнере | LM Studio слушает только `127.0.0.1` | Включить в настройках сервера LM Studio прослушивание на `0.0.0.0` / разрешить LAN-доступ |
| SearXNG не отвечает | Первый запуск генерирует ключи и может занять время | Подождать и повторить `docker compose restart searxng` |
| Порт 8000 занят | Другое приложение на хосте | Сменить `"8000:8000"` в `docker-compose.yml` на свободный порт |

## Host-режим (отладка, приложение вне контейнера)

Требуется Python 3.13 + Docker (только SearXNG).

- [ ] `python -m venv venv`
- [ ] Windows: `.\venv\Scripts\python.exe -m pip install -r requirements.txt`
  Mac: `venv/bin/python -m pip install -r requirements.txt`
- [ ] `docker compose up -d searxng`
- [ ] `uvicorn app.main:app --reload` (конфиг по умолчанию уже указывает на localhost:8888 и localhost:1234)
- [ ] Открыть `http://localhost:8000`

Переменные для переопределения — в `cultural-history-app/.env.example`.
