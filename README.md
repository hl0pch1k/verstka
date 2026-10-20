<a id="top"></a>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/hero-dark.svg">
    <img src="docs/readme/svg/hero-light.svg" width="100%" alt="Verstka — логотип интерфейса «Слои», ЛЦТ 2026, кейс VK Tech № 4, вторая ступень, команда «Рекрут 2». Справа три плиты: 01 Шаблон, 02 Текст и данные, 03 Три варианта — структурный, визуальный, компактный">
  </picture>
</p>

<p align="center">
  <a href=".github/workflows/linux.yml"><img src="docs/readme/svg/badge-ci.svg" height="26" alt="CI: Linux · Ubuntu 24.04"></a>
  <a href="pyproject.toml"><img src="docs/readme/svg/badge-python.svg" height="26" alt="Python 3.11 · 3.12"></a>
  <a href="web"><img src="docs/readme/svg/badge-web.svg" height="26" alt="Интерфейс: React · TypeScript"></a>
  <a href="MODELS.md"><img src="docs/readme/svg/badge-llm.svg" height="26" alt="Модель: Qwen3.8-27B · инференс VK"></a>
  <a href="MODELS.md#изображения-внутри-слайдов-t2i"><img src="docs/readme/svg/badge-t2i.svg" height="26" alt="Картинки: Z-Image · Polza"></a>
  <a href="LICENSE"><img src="docs/readme/svg/badge-license.svg" height="26" alt="Лицензия: MIT"></a>
</p>

| Содержание<br><img src="docs/readme/svg/spacer.svg" width="330" height="1" alt=""> | Что там<br><img src="docs/readme/svg/spacer.svg" width="470" height="1" alt=""> |
|---|---|
| 01 · [Интерфейс](#interface) | экраны сервиса и [Помощник](#helper) — правки презентации словами |
| 02 · [Примеры презентаций](#examples) | готовые колоды — PDF и PPTX |
| 03 · [Видео и презентация](#video) | скринкаст второй ступени и [презентация решения](#presentation) — PDF и PPTX |
| 04 · [Что умеет](#features) | данные, брендбук, база знаний, любой вход, картинки |
| 05 · [Как это работает](#how) | восемь шагов от файлов до PPTX |
| 06 · [Качество](#quality) | проверки, время сборки, тесты |
| 07 · [Быстрый старт](#start) | запуск на своей машине |
| 08 · [Модели и стоимость](#models) | открытые модели и расход |
| 09 · [Соответствие ТЗ](#tz) | требования обеих ступеней по пунктам |
| 10 · [Документация](#docs) | архитектура, модели, проверки, ограничения |

<br>
<br>

<a id="interface"></a><a id="как-это-выглядит"></a>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/section-01-interface-dark.svg">
  <img src="docs/readme/svg/section-01-interface-light.svg" width="100%" alt="01 · Интерфейс">
</picture>

Интерфейс «Слои» — веб-интерфейс сервиса: путь «Создать → Сборка → Результат → Правки» идёт на одном экране, плиты-слои сменяют друг друга.

<br>

<p align="center">
  <img src="docs/readme/showcase/ui-result.webp" width="100%" alt="Результат: колода «Закрытие Q3 2026 — VK Cloud» на шаблоне VK Tech с брендбуком VK Cloud — 89 из 100, ошибок нет, 3 предупреждения; оценки трёх вариантов и кнопка «Скачать PowerPoint»">
</p>

<br>

<p align="center">
  <img src="docs/readme/showcase/ui-create.webp" width="49%" alt="Создать: плита «01 Шаблон» с брендбуком, «02 Текст» с тремя файлами данных и базой знаний, «03 Параметры и запуск»">
  <img src="docs/readme/showcase/ui-brand.webp" width="49%" alt="Брендбук VK Cloud: палитра, шрифты и расхождения с шаблоном VK Tech с переключателем «Брендбук / Шаблон»">
</p>

<p align="center">
  <img src="docs/readme/showcase/ui-build.webp" width="49%" alt="Сборка: раскладка слайдов эскизами и «Как думает агент» — дизайнер, вёрстка, проверка, взгляд дизайнера">
  <img src="docs/readme/showcase/ui-why.webp" width="49%" alt="Почему так: профиль файла «Хранилище Q2 и Q3.csv» и три варианта визуализации с причинами — выбраны сгруппированные полосы">
</p>

<p align="center">
  <img src="docs/readme/showcase/ui-quality.webp" width="49%" alt="Подробнее → Качество: 87 из 100, ошибок нет, 3 предупреждения, замечания по слайдам и «Взгляд дизайнера»">
  <img src="docs/readme/showcase/ui-agent.webp" width="49%" alt="Подробнее → Агент: как работал агент — автор по базе знаний, аналитик по данным — и история правок">
</p>

<p align="center">
  <img src="docs/readme/showcase/ui-helper.webp" width="49%" alt="Помощник открыт: просьба «на слайде 5 выдели Госсектор цветом», ответ «выделил „Госсектор“ цветом, 87 → 89» и «Показать слайд 5»">
  <img src="docs/readme/showcase/ui-remarks.webp" width="49%" alt="Замечания и «Исправить слайд»: замечание проверки рамкой прямо на слайде и кнопка «Исправить слайд»">
</p>

<p align="center">
  <img src="docs/readme/showcase/ui-unseen.webp" width="49%" alt="Сторонний шаблон Growing Liberty: «Итоги университета за 2026 год», 88 из 100, ошибок нет">
  <img src="docs/readme/showcase/ui-history.webp" width="49%" alt="Мои презентации: три колоды за сегодня с шаблоном, числом слайдов и оценкой">
</p>

<br>

<p align="center">
  <img src="docs/readme/showcase/ui-phone.webp" width="100%" alt="Телефон — в разработке: три экрана мобильной версии «Слоёв» в рамках телефона — «Создать», «Сборка» с ходом мысли агента и «Результат» с оценкой и кнопкой «Скачать PowerPoint»">
</p>

Мобильная версия интерфейса — в разработке; сейчас сервис работает в браузере на компьютере.

<br>

<a id="helper"></a><a id="помощник"></a>

### Помощник

Помощник — агент в чате, который правит готовую презентацию **словами**. Можно назвать номер слайда или сказать «этот слайд»; несколько просьб подряд встают в очередь.

- «на слайде 5 итог Q3 к Q2 в процентах, выдели падение» → пересчитал, выделил падение, переписал вывод.
- «на слайде 6 выдели Госсектор цветом» → выделил категорию на диаграмме.
- «на слайде 6 добавь картинку: инженеры в серверной» → перестроил слайд под картинку.
- «сделай слайд короче» → сократил текст, числа остались.
- «почему слайд 4 такой?» → открыл объяснение «Почему так» для этого слайда.

Замечания проверки исправляет кнопка «Исправить слайд», просьба «исправь всё» — во всех вариантах сразу, а «верни как было» отменяет правку.

<br>

<p align="center">
  <img src="docs/readme/showcase/helper-1-q3-q2.webp" width="100%" alt="Просьба «на слайде 5 итог Q3 к Q2 в процентах, выдели падение»: до — «Выручка Q3 выше Q2 у 2 из 3 сервисов»; после — «Выручка Q3 — 334 млн ₽, +7,4% к Q2; резервное копирование снизилось на 8,6%», Q2 и Q3 рядом, крупно −8,6%">
</p>

<br>

<p align="center">
  <img src="docs/readme/showcase/helper-2-picture.webp" width="100%" alt="Просьба «на слайде 6 добавь картинку: инженеры в серверной»: до — слайд «Команда PaaS укладывается в план» из двух колонок текста; после — тот же текст рядом с картинкой во всю высоту слайда">
</p>

<br>

<p align="center">
  <img src="docs/readme/showcase/helper-3-chat.webp" width="100%" alt="Чат Помощника: очередь из двух просьб, ответ на «добавь картинку» с итогом правки и кнопками «Верни как было» и «Почему слайд 6 такой?», просьба «исправь всё» с ходом исправления трёх вариантов">
</p>

<br>
<br>

<a id="examples"></a>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/section-02-examples-dark.svg">
  <img src="docs/readme/svg/section-02-examples-light.svg" width="100%" alt="02 · Примеры презентаций">
</picture>

Колоды собраны 20.10 с моделью на инференсе VK, слайды — без правок руками. Нажмите на карточку, чтобы открыть PDF.

<br>

<p align="center">
  <a href="examples/showcase/01-data-brandbook/deck.pdf"><img src="docs/readme/showcase/01-data-brandbook.webp" width="100%" alt="Итоги продаж VK Cloud на шаблоне VK Tech с брендбуком VK Cloud: ключевые показатели с выводом «Выручка растёт быстрее числа клиентов: +23% против +18%», линейный график выручки по месяцам, ранжированные столбцы восьми регионов, кольцо долей каналов, гистограмма времени ответа поддержки и NPS с разрывами на месте пропусков"></a>
</p>

**01 · Данные + брендбук** — 7 файлов продаж и брендбук VK Cloud → отчёт правлению, где у каждого графика заголовок-вывод. [PDF](examples/showcase/01-data-brandbook/deck.pdf) · [бриф](examples/showcase/01-data-brandbook/input.txt) · [то же на шаблоне ЛЦТ](examples/showcase/01-data-brandbook/deck-lct.pdf)

<br>

<p align="center">
  <a href="examples/showcase/02-data-knowledge/deck.pdf"><img src="docs/readme/showcase/02-data-knowledge.webp" width="100%" alt="Итоги Q3 «Склад24» для совета директоров на шаблоне ЛЦТ 2026: «MRR 1,82 млн ₽ — 61 % цели 3 млн ₽», «Ежемесячный отток 5,2 % — выше цели 3 %», деньги и запас на 9 месяцев, линейный график MRR с января по сентябрь"></a>
</p>

**02 · Таблица + база знаний** — показатели в Excel и инвестмеморандум → отчёт совету «факт против цели». [PDF](examples/showcase/02-data-knowledge/deck.pdf) · [план](examples/showcase/02-data-knowledge/input.txt) · [таблица](examples/showcase/02-data-knowledge/sklad24_q3.xlsx) · [база знаний](examples/showcase/02-data-knowledge/investmemorandum_sklad24.docx)

<br>

<p align="center">
  <a href="examples/showcase/03-vk-tech-ml-platform/deck.pdf"><img src="docs/readme/showcase/03-vk-tech-ml-platform.webp" width="100%" alt="ML Platform для ритейла на шаблоне VK Tech: обложка, слайд с картинкой и крупными цифрами 340 магазинов и 12 регионов, график «Списания снизились с 5,1 до 3,4 % оборота», план запуска в три шага"></a>
</p>

**03 · Готовый текст** — 255 слов о запуске продукта → питч на 15 слайдов с двумя картинками. [PDF](examples/showcase/03-vk-tech-ml-platform/deck.pdf) · [вход](examples/showcase/03-vk-tech-ml-platform/input.txt)

<br>

<p align="center">
  <a href="examples/showcase/04-workspace-migration/deck.pdf"><img src="docs/readme/showcase/04-workspace-migration.webp" width="100%" alt="Миграция «Северного порта» на шаблоне VK WorkSpace: тёмная обложка, крупные цифры 41 ТБ, 96 млн, 2,3 млн, 0,3 %, слайд «Было / Стало» и итог «расходы снизились на 38 %»"></a>
</p>

**04 · Длинный доклад** — выступление на 611 слов → колода для конференции в стиле VK WorkSpace. [PDF](examples/showcase/04-workspace-migration/deck.pdf) · [вход](examples/showcase/04-workspace-migration/input.txt)

<br>

<p align="center">
  <a href="examples/showcase/05-lct-pitch/deck.pdf"><img src="docs/readme/showcase/05-lct-pitch.webp" width="100%" alt="Питч «ТрубаСкан» на шаблоне ЛЦТ 2026: фиолетовая обложка, процесс из пяти шагов, ключевые цифры 14, 380, 1 260 и крупное «19 дней»"></a>
</p>

**05 · Питч на хакатон** — текст команды на 607 слов → 15 слайдов на шаблоне ЛЦТ. [PDF](examples/showcase/05-lct-pitch/deck.pdf) · [вход](examples/showcase/05-lct-pitch/input.txt)

<br>

<p align="center">
  <a href="examples/showcase/06-education-lesson/deck.pdf"><img src="docs/readme/showcase/06-education-lesson.webp" width="100%" alt="Урок «Как сообщение доходит от тебя до друга» на шаблоне VK Education: обложка, слайд с картинкой телефона, путь пакетов через роутеры в пять шагов и сборка сообщения в четыре шага"></a>
</p>

**06 · План урока** — урок информатики для 7 класса → 12 слайдов с картинкой по смыслу. [PDF](examples/showcase/06-education-lesson/deck.pdf) · [вход](examples/showcase/06-education-lesson/input.txt)

<br>

<p align="center">
  <a href="examples/showcase/07-unseen-template/deck.pdf"><img src="docs/readme/showcase/07-unseen-template.webp" width="100%" alt="Бизнес-план фитнес-студии на незнакомом шаблоне LibreOffice «Vivid»: крупные цифры цели, круговая диаграмма критериев выбора, воронка с картинкой и два линейных графика роста клиентов и прибыли"></a>
</p>

**07 · Незнакомый шаблон** — бизнес-план и шаблон LibreOffice, которого сервис раньше не видел → колода с подобранными шрифтами и диаграммами. [PDF](examples/showcase/07-unseen-template/deck.pdf) · [PPTX](examples/showcase/07-unseen-template/deck.pptx)

<details>
<summary><b>Ещё примеры в репозитории</b></summary>

- Данные и брендбук для своих проверок — [`data-sales-2026`](examples/data-sales-2026), [`data-science-2026`](examples/data-science-2026), [`brandbook-vk-cloud`](examples/brandbook-vk-cloud).
- Девять презентаций первой ступени — [`examples/outputs`](examples/outputs).
- Брифы и планы в разных формах — [`examples/briefs`](examples/briefs), [`tests/fixtures/plans`](tests/fixtures/plans).

</details>

<br>
<br>

<a id="video"></a>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/section-03-video-dark.svg">
  <img src="docs/readme/svg/section-03-video-light.svg" width="100%" alt="03 · Видео и презентация">
</picture>

<p align="center">
  <a href="https://cdn.jsdelivr.net/gh/hl0pch1k/verstka@c0aebe9/docs/video/verstka-stage2.mp4"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/video-stage2-dark.svg"><img src="docs/readme/svg/video-stage2-light.svg" width="49%" alt="Вторая ступень — текущее решение: 20.10, 9 минут 44 секунды — смотреть"></picture></a>
  <a href="https://cdn.jsdelivr.net/gh/hl0pch1k/verstka@21c4283/docs/video/verstka-demo.mp4"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/video-stage1-dark.svg"><img src="docs/readme/svg/video-stage1-light.svg" width="49%" alt="Первая ступень — прошлая версия: 29.09, 8 минут 54 секунды — смотреть"></picture></a>
</p>

- **Актуальная версия** — скринкаст второй ступени, это текущее решение: шаблон VK Tech с брендбуком, данными и базой знаний, «Почему так», правки Помощником, сторонний шаблон. [Смотреть](https://cdn.jsdelivr.net/gh/hl0pch1k/verstka@c0aebe9/docs/video/verstka-stage2.mp4) · [что в видео по минутам](docs/video/README.md#вторая-ступень)
- Архив — видео первой ступени (29.09): прошлая версия сервиса и прежний интерфейс. [Смотреть](https://cdn.jsdelivr.net/gh/hl0pch1k/verstka@21c4283/docs/video/verstka-demo.mp4) · [по минутам](docs/video/README.md#первая-ступень)

<br>

<a id="presentation"></a>

<p align="center">
  <a href="docs/presentation/verstka-pitch-stage2.pdf"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/pitch-dark.svg"><img src="docs/readme/svg/pitch-light.svg" width="99%" alt="Презентация решения: 20.10, 19 слайдов на шаблоне ЛЦТ — смотреть"></picture></a>
</p>

**Презентация решения** — 19 слайдов на шаблоне ЛЦТ: команда, проблема, как работает Verstka, данные и графики, брендбук, правки, качество, планы. [PDF](docs/presentation/verstka-pitch-stage2.pdf) · [PPTX](docs/presentation/verstka-pitch-stage2.pptx)

<br>

<p align="center">
  <img src="docs/images/build.gif" width="100%" alt="Сборка «Интеграла» в интерфейсе «Слои»: текст по теме, аналитик, дизайнер, критик, раскладка по макетам, взгляд дизайнера и готовый результат">
</p>

Агент работает на виду: читает вход, продумывает слайды, верстает и проверяет себя.

<br>
<br>

<a id="features"></a><a id="что-умеет"></a>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/section-04-features-dark.svg">
  <img src="docs/readme/svg/section-04-features-light.svg" width="100%" alt="04 · Что умеет">
</picture>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/features-dark.svg">
    <img src="docs/readme/svg/features-light.svg" width="100%" alt="Шесть возможностей: данные в выводы (профиль, задача, 2–3 вида с причинами, заголовок с числом); любой брендбук (PDF, токены, Figma, .fig, ZIP — бренд побеждает шаблон); база знаний (документы и ссылки, источник в заметках, сверка с таблицами); любой вход (план, письмо, DOCX, PDF, тема, готовая презентация, дословно); картинки по смыслу (Z-Image в палитре шаблона, без надписей); правки и Помощник">
  </picture>
</p>

<br>

<a id="вторая-ступень-данные-и-брендбук"></a>

#### Данные → выводы

- Сам выбирает, как показать данные — линией, столбцами, долями или таблицей — и объясняет выбор.
- Заголовок слайда — **вывод с числом**, а не тема.
- Перепроверяет каждое число по исходной таблице; чего в данных нет, так и говорит.

<br>

#### Любой брендбук

- PDF, токены, ссылка Figma, файл `.fig`, папка или архив.
- Цвета, шрифты и логотип бренда ложатся на копию шаблона; при расхождении побеждает бренд.

<br>

#### База знаний

- Документы и ссылки, по которым агент пишет текст и сверяет факты.
- Источник каждого утверждения — в заметках к слайду.

<br>

#### Любой вход

- План, письмо, тезисы, DOCX или PDF, короткая тема, готовая презентация.
- Свой текст можно разложить дословно, без пересказа.

<br>

#### Картинки по смыслу

- Появляются там, где их просит автор или где заголовок называет предмет, — в палитре шаблона.
- Картинку с надписью модель зрения отбраковывает и рисует заново.

<br>

#### Правки и Помощник

- «Исправить слайд» — одной кнопкой по замечанию.
- Правки словами: «покажи таблицей», «короче», «почему слайд 4 такой».

<br>
<br>

<a id="how"></a><a id="как-устроено"></a>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/section-05-how-dark.svg">
  <img src="docs/readme/svg/section-05-how-light.svg" width="100%" alt="05 · Как это работает">
</picture>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/pipeline-dark.svg">
    <img src="docs/readme/svg/pipeline-light.svg" width="100%" alt="Конвейер Verstka: 01 Чтение — шаблон в manifest.json, текст, документы, данные; 02 План — агент: аналитик, дизайнер, критик; 03 Смысл — каждое число сверено со входом; 04 Данные — профиль, задача, вид, вывод с числом; 05 Вёрстка на слайды-образцы шаблона и бренда; 06 Картинки — Z-Image с проверкой зрением; 07 Аудит — 73 + 3 проверки и автоисправление; 08 Экспорт — PPTX, PDF, HTML. Синие точки — шаги модели, тёмные — шаги кода">
  </picture>
</p>

- Шаблон разбирается один раз: палитра, шрифты, сетка, макеты.
- Агент решает, какие нужны слайды; числа считает и сверяет код.
- Вёрстка идёт по слайдам-образцам шаблона, потом проверка качества и автоисправление.
- Промпты и настройки лежат отдельными файлами с версиями. Подробно — [ARCHITECTURE.md](ARCHITECTURE.md).

<br>
<br>

<a id="quality"></a>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/section-06-quality-dark.svg">
  <img src="docs/readme/svg/section-06-quality-light.svg" width="100%" alt="06 · Качество">
</picture>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/quality-dark.svg">
    <img src="docs/readme/svg/quality-light.svg" width="100%" alt="Качество в цифрах: 76 проверок качества (73 кодом и 3 моделью); до 5 минут на три варианта, колода с данными — 26–80 секунд; 6 098 тестов (5 294 модульных, 48 интеграционных, 756 интерфейса); ноль закрытых API">
  </picture>
</p>

- Проверки смотрят вёрстку, шаблон, смысл и графики; замечания видны прямо на слайде. Список — [AUDIT.md](AUDIT.md).
- Автоисправление откатывает правку, если после неё стало хуже.
- Тесты не ходят в сеть; CI на Ubuntu 24.04 повторяет быстрый старт с нуля.

<br>
<br>

<a id="start"></a><a id="запуск"></a>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/section-07-start-dark.svg">
  <img src="docs/readme/svg/section-07-start-light.svg" width="100%" alt="07 · Быстрый старт">
</picture>

Постоянного стенда нет: сервис запускается на своём компьютере примерно за 15 минут — Linux (Ubuntu 24.04) или macOS; на Windows — внутри WSL 2. Видеокарта не нужна: модели работают в облаке.

**1. Установите программы** — Python, Node.js, LibreOffice (для картинок слайдов и PDF) и Git.

```bash
# Ubuntu 24.04 (Node.js 20 — из NodeSource: в стандартном репозитории 18)
sudo apt-get update && sudo apt-get install -y git python3-venv python3-pip libreoffice-impress poppler-utils
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs

# macOS (Homebrew)
brew install python@3.11 node poppler git && brew install --cask libreoffice
```

**2. Скачайте код и установите зависимости**

```bash
git clone https://github.com/hl0pch1k/verstka.git && cd verstka
python3 -m venv .venv            # на macOS: python3.11 -m venv .venv
source .venv/bin/activate        # в каждом новом окне терминала
pip install --upgrade pip && pip install -e ".[api,dev]"
cd web && npm install && npm run build && cd ..
cp verstka/fonts/Play-*.ttf ~/Library/Fonts/   # только macOS: шрифт шаблонов VK для превью LibreOffice
```

**3. Проверьте, что всё работает** — без ключей и без моделей, около 15 секунд. Готовая презентация появится в папке `out/check`.

```bash
verstka generate -t tests/fixtures/tpl_audit/templates/lo_focus.pptx -b examples/briefs/fitness_studio.md -o out/check --no-llm --no-vlm --export all
```

**4. Добавьте ключи моделей.** Скопируйте шаблон настроек: `cp .env.example .env`. Откройте `.env` в любом редакторе, уберите `#` в начале строк с ключами VK и впишите значения:

```
VK_INFERENCE_API_KEY=     # инференс VK
VK_PROJECT_ID=
POLZA_API_KEY=            # картинки и запасной путь, если VK не отвечает
```

Проверьте, что модель отвечает: соберите ту же презентацию с моделью и посмотрите, кто составил план.

```bash
verstka generate -t tests/fixtures/tpl_audit/templates/lo_focus.pptx -b examples/briefs/fitness_studio.md -o out/model_check
python -c "import json; p = json.load(open('out/model_check/structured/run_manifest.json'))['planner']; print(p['planned_by'], p.get('model'))"
# «model qwen38-27b-fp8» или «agent …» — модель ответила и составила план; «rules None» — модель недоступна, презентация собрана без неё
```

**5. Запустите веб-интерфейс** и откройте в браузере http://127.0.0.1:8000

```bash
verstka serve                    # интерфейс — http://127.0.0.1:8000, описание API — http://127.0.0.1:8000/docs
```

Шаблоны VK из датасета кейса загрузите в интерфейсе: плита «01 Шаблон» → «Загрузить свой». Можно загрузить и любой другой шаблон PowerPoint.

<a id="как-проверить"></a>

**6. Для разработчиков: каждый вид входа из командной строки**

```bash
T=tests/fixtures/tpl_audit/templates/lo_focus.pptx     # незнакомый шаблон LibreOffice из репозитория
verstka generate -t $T -b tests/fixtures/plans/warehouse_email.md -o out/plan --no-llm --no-vlm          # план письмом
verstka generate -t $T -b tests/fixtures/documents/report.docx -o out/docx --no-llm --no-vlm             # документ DOCX (или .pdf)
echo "Сделай презентацию о результатах третьего квартала для правления" > brief.md
verstka generate -t $T -b brief.md --kb tests/fixtures/documents/kb -o out/kb --no-llm --no-vlm          # тема + база знаний
verstka generate -t $T --data examples/data-sales-2026 --brand examples/brandbook-vk-cloud/guideline.pdf \
  -o out/data --no-llm --no-vlm                                                                         # данные + брендбук
```

**7. Тесты** — интеграционным тестам нужны шаблоны VK: папка `Датасет` рядом с папкой репозитория или путь в `VERSTKA_FIXTURES_DIR`.

```bash
pytest tests/unit            # модульные
pytest tests/integration     # полный пайплайн на шаблонах VK и ЛЦТ
cd web && npm test           # интерфейс
```

<details>
<summary><b>Переменные окружения</b></summary>

| Переменная | Что задаёт | По умолчанию |
|---|---|---|
| `VK_INFERENCE_API_KEY`, `VK_PROJECT_ID` | инференс VK: при обоих включается профиль `configs/models.vk.yaml` | профиль Polza |
| `POLZA_API_KEY` | Polza.ai: Qwen3.8-27B, Qwen3.6-27B, Z-Image; с ключами VK — запасной путь и картинки | без моделей, места под картинки свободны |
| `VERSTKA_MODELS` | принудительно выбрать профиль (`configs/models.vk.yaml` или `configs/models.yaml`), важнее ключей VK | по ключам |
| `VK_T2I_MODEL` | собственная модель изображений VK, если появится; Z-Image отвечает после неё | Z-Image на Polza |
| `VERSTKA_WORKSPACE` | кэш шаблонов, генераций, данных, брендбуков, баз знаний | `./workspace` |
| `FIGMA_TOKEN` | брендбук по ссылке Figma | ссылка Figma не читается |
| `VERSTKA_WIKI`, `VERSTKA_WRITER` | `0` — писатель по теме без Википедии / выключен | включены |
| `VERSTKA_MAX_*_MB` | пределы загрузки: `UPLOAD` (шаблон), `DATA`, `XLSX`, `TEXT`, `BRAND`, `DOC`, `KB_UPLOAD` | 200, 25, 4, 15, 50, 25, 100 |
| `VERSTKA_SOFFICE` | путь к LibreOffice в нестандартном месте | поиск в `PATH`, приложении macOS, `/opt/libreofficeX.Y` |
| `VERSTKA_CORS_ORIGINS` | адреса для API из другого источника | сервер разработки Vite |

</details>

<br>
<br>

<a id="models"></a>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/section-08-models-dark.svg">
  <img src="docs/readme/svg/section-08-models-light.svg" width="100%" alt="08 · Модели и стоимость">
</picture>

- Текст и зрение — Qwen3.8-27B на инференсе VK; если VK не ответил, та же модель на Polza.
- Картинки — Z-Image на Polza, 1,40 ₽ за картинку.
- Обе модели — открытые веса под Apache 2.0, закрытых API нет. Без ключей сервис работает без моделей.
- Роли, промпты и расход — [MODELS.md](MODELS.md).

<br>
<br>

<a id="tz"></a><a id="соответствие-тз"></a>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/section-09-tz-dark.svg">
  <img src="docs/readme/svg/section-09-tz-light.svg" width="100%" alt="09 · Соответствие ТЗ">
</picture>

✅ — сделано, ◐ — частично.

| Требование | | Где показано |
|---|:-:|---|
| Разбор шаблона: токены, макеты, правила | ✅ | [`analysis/`](verstka/analysis), «Подробнее» → «Шаблон» |
| Структура и текст по брифу | ✅ | [`planning/`](verstka/planning), [Примеры](#examples) |
| Слайды по шаблону и контент-пакету | ✅ | слайды-образцы и фигуры шаблона |
| Графики, таблицы, диаграммы | ✅ | нативные объекты PowerPoint, [Примеры](#examples) |
| Генерация изображений | ✅ | Z-Image, [MODELS.md](MODELS.md) |
| Версии скиллов и агентов | ✅ | [`skills/`](skills), `run_manifest.json` |
| Три варианта с разной подачей | ✅ | [`strategies.yaml`](configs/strategies.yaml) |
| Аудит с визуализацией и исправлением | ✅ | [AUDIT.md](AUDIT.md), [Качество](#quality) |
| Экспорт PPTX, PDF, HTML | ✅ | [`export/`](verstka/export) |
| 10–15 слайдов или заданное число | ✅ | число берётся из текста или параметра |
| До 5 минут на сборку | ✅ | [Качество](#quality) |
| Не заточено под три шаблона | ✅ | [07 · Незнакомый шаблон](#examples), [`test_unseen_templates_guard.py`](tests/unit/test_unseen_templates_guard.py) |
| Десктопный веб | ✅ | интерфейс «Слои» |
| Chrome, Firefox, Safari, Яндекс Браузер | ◐ | проверено в Chrome и Safari |
| Открытые модели на инференсе VK | ✅ | [Модели](#models) |
| Профиль данных и 2–3 вида с причинами | ✅ | [`data/`](verstka/data), «Почему так» |
| Заголовки-выводы, оси, единицы, источник | ✅ | [01 · Данные + брендбук](#examples) |
| Агрегация больших данных | ✅ | [`aggregate.py`](verstka/data/aggregate.py) |
| Вид графика — по данным, а не по формату файла | ✅ | одни данные в CSV, XLSX и JSON дают один вид (тесты) |
| Брендбук важнее шаблона | ✅ | [`brand/`](verstka/brand), [01 · Данные + брендбук](#examples) |
| Наборы данных и брендбуки для проверки | ✅ | [`examples/`](examples) |
| Документация, промпты и конфиги отдельно | ✅ | [Документация](#docs), [`configs/`](configs) |

<br>
<br>

<a id="docs"></a>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/readme/svg/section-10-docs-dark.svg">
  <img src="docs/readme/svg/section-10-docs-light.svg" width="100%" alt="10 · Документация и ограничения">
</picture>

Подробно: [ARCHITECTURE.md](ARCHITECTURE.md) — устройство · [MODELS.md](MODELS.md) — модели и расход · [AUDIT.md](AUDIT.md) — проверки и тесты · [видео первой ступени](docs/video/README.md) · [питч первой ступени](docs/presentation/verstka-pitch.pdf) · [исходники графики README](docs/readme/source).

Чего пока нет:

- Интерфейс рассчитан на компьютер; Firefox и Яндекс Браузер не проверялись.
- Без модели тексты проще: заголовки берутся из фраз самого текста.
- На сложный вопрос к данным колода может не ответить — и прямо об этом скажет.
- Три варианта колоды с данными различаются вёрсткой, текст у них общий.
- Превью и PDF рисует LibreOffice: шрифт, которого нет ни в системе, ни в файле, заменяется.

Лицензия — MIT ([`LICENSE`](LICENSE)). Шрифты в [`verstka/fonts/`](verstka/fonts) — SIL OFL 1.1.

<p align="right"><a href="#top">↑ наверх</a></p>
