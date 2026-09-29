# Прогон из видео

Файлы генерации, которая записана в [`docs/video/verstka-demo.mp4`](../../../docs/video/verstka-demo.mp4): один непрерывный прогон живого сервиса в браузере, без монтажа и ускорения.

| | |
|---|---|
| Шаблон | «Blue and Green Business Infographic» с [SlidesCarnival](https://www.slidescarnival.com): его нет в датасете и в регрессионном корпусе, сервис его никогда не видел и под него не настраивался. Файл шаблона сюда не положен (он распространяется на условиях SlidesCarnival), в PPTX-файлах ниже — его мастера, макеты и тема |
| Текст | [`examples/briefs/verstka_final_pitch.md`](../../briefs/verstka_final_pitch.md), 10 слайдов с текстом докладчика |
| Время | 71 секунда от нажатия «Создать презентацию» до трёх готовых вариантов (лимит — 5 минут) |
| Оценка проверки качества | 100 · 100 · 100: ошибок и предупреждений нет, сверено 36, 34 и 38 чисел, лишних нет |
| Модель | `Qwen/Qwen3-32B` через Cloud.ru Foundation Models (открытые веса, Apache 2.0); настройки — [MODELS.md](../../../MODELS.md#сервис-api-модель-и-настройки-демо-прогонов) |
| Правка в чате | «На слайде 10: сделай из пунктов три карточки» — 12 секунд, переделан только слайд 10 структурного варианта (`structured/edits.json`) |

| Вариант | PowerPoint | PDF | Веб | Проверка качества | Паспорт запуска |
|---|---|---|---|---|---|
| Структурный | [`deck.pptx`](structured/deck.pptx) | [`deck.pdf`](structured/deck.pdf) | [`deck.html`](structured/deck.html) | [`audit_report.json`](structured/audit_report.json) | [`run_manifest.json`](structured/run_manifest.json) |
| Визуальный | [`deck.pptx`](visual/deck.pptx) | [`deck.pdf`](visual/deck.pdf) | [`deck.html`](visual/deck.html) | [`audit_report.json`](visual/audit_report.json) | [`run_manifest.json`](visual/run_manifest.json) |
| Компактный | [`deck.pptx`](compact/deck.pptx) | [`deck.pdf`](compact/deck.pdf) | [`deck.html`](compact/deck.html) | [`audit_report.json`](compact/audit_report.json) | [`run_manifest.json`](compact/run_manifest.json) |

Рядом с каждым вариантом — план агента (`outline.json`, `planner_raw.json`) и подбор макетов (`layout_plan.json`); ход работы агента — [`agent.json`](agent.json), параметры генерации — [`generation.json`](generation.json).
