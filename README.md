# Verstka

Сервис «Цифровой дизайнер презентаций»: читает произвольный PPTX как набор правил (дизайн-токены, паттерны слайдов, компоненты, ассеты) и собирает по ним новые презентации в трёх вариантах вёрстки с аудитом и экспортом в PPTX, PDF и HTML.

Кейс № 4 хакатона «Лидеры цифровой трансформации 2026» от VK Tech.

## Установка

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,api]"
```

Системные зависимости: LibreOffice (`soffice`) и poppler (`pdftoppm`) для рендера слайдов.

## Переменные окружения

| Переменная | Назначение |
|---|---|
| `OPENROUTER_API_KEY` | ключ OpenAI-совместимого провайдера (OpenRouter по умолчанию, см. `configs/models.yaml`) |
| `VERSTKA_WORKSPACE` | папка кэша анализа шаблонов (по умолчанию `./workspace`) |
| `VERSTKA_FIXTURES_DIR` | папка с шаблонами для интеграционных тестов |

## Быстрый старт

```bash
verstka analyze path/to/template.pptx          # разбор шаблона → workspace/templates/<id>/manifest.json + gallery.html
verstka analyze path/to/template.pptx --no-llm --no-vlm   # только детерминированный разбор
```

## Тесты

```bash
pytest
```

Документы: `ARCHITECTURE.md`, `MODELS.md`, `AUDIT.md` (появятся по мере реализации), спек в `docs/superpowers/specs/`.
