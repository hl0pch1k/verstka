# Прогоны из видео

Файлы двух генераций из [`docs/video/verstka-demo.mp4`](../../../docs/video/verstka-demo.mp4): один непрерывный дубль живого сервиса, без монтажа и ускорения. Текст в обоих прогонах один — [`examples/briefs/verstka_final_pitch.md`](../../briefs/verstka_final_pitch.md), 10 слайдов с текстом докладчика.

| | Часть 1 · шаблон датасета | Часть 2 · незнакомый шаблон |
|---|---|---|
| Шаблон | VK Tech из датасета кейса | «Dark Minimalist Business» с [SlidesCarnival](https://www.slidescarnival.com): его нет в датасете и в регрессионном корпусе, под него ничего не настраивалось. Файл шаблона сюда не положен (он распространяется на условиях SlidesCarnival), в PPTX ниже — его мастера, макеты и тема |
| Три варианта от нажатия «Создать» | 85 секунд | 65 секунд |
| Проверка качества | 100 · 100 · 100, ошибок и предупреждений нет; сверено 28, 26 и 30 чисел | 100 · 100 · 100, ошибок и предупреждений нет; сверено 30, 27 и 31 число |
| Модель | `Qwen/Qwen3-32B` через Cloud.ru Foundation Models | то же |
| Файлы | [`vktech/`](vktech) | [`dark-minimalist/`](dark-minimalist) |

Правка в чате во второй части: «На слайде 10: сделай из пунктов три карточки» — 26 секунд, переделан только слайд 10 структурного варианта ([`dark-minimalist/structured/edits.json`](dark-minimalist/structured/edits.json)).

В каждой папке — три варианта (`structured`, `visual`, `compact`): `deck.pptx`, `deck.pdf`, `deck.html`, отчёт проверки `audit_report.json`, паспорт запуска `run_manifest.json`, план агента `outline.json` и `planner_raw.json`, подбор макетов `layout_plan.json`; рядом — ход работы агента `agent.json` и параметры генерации `generation.json`. Настройки модели — в [MODELS.md](../../../MODELS.md#сервис-api-модель-и-настройки-демо-прогонов).
