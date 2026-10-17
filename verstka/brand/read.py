"""`read_brandbook(source)` — брендбук любого вида → `BrandSpec`.

- ссылка на Figma → REST API (`FIGMA_TOKEN`), см. `figma.py`;
- папка → `folder.read_folder`; `.zip` → `folder.read_zip`;
- `.json` → токены (W3C, Tokens Studio, Style Dictionary, плоский, переменные Figma), см. `tokens.py`;
- `.pdf` → гайдлайн по тексту, с `use_vlm` — ещё и моделью по картинкам страниц, см. `pdf.py`;
- `.pptx` / `.potx`, `.svg` / `.png` / `.jpg` — как папка из одного файла (тема презентации, логотип);
- `.fig` и прочее — понятная ошибка.

Ошибки — `BrandReadError` с текстом для человека. `on_step(что, итог)` получает шаги разбора для интерфейса
(«открыт файл: 12 страниц», «палитра: 6 цветов», «шрифты: VK Sans Display, VK Sans Text», «логотипы: 4», «правила: 13»)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Optional

from verstka.brand.common import STEP_KEYS, BrandReadError, StepReporter, step_partials, step_texts
from verstka.brand.figma import FIG_FILE, normalize_url, read_figma_url
from verstka.brand.folder import read_collection, read_folder, read_zip
from verstka.brand.pdf import read_pdf
from verstka.brand.tokens import read_tokens
from verstka.schemas.brand import BrandSpec

SUPPORTED = ".json, .pdf, .zip, .pptx, .potx, .svg, .png, .jpg, папка или ссылка на Figma"
NO_LOGO_FILES = "Файлов логотипа в брендбуке нет — логотип останется из шаблона, а где его нет, логотипа не будет."
_IMAGE_EXT = {".svg", ".png", ".jpg", ".jpeg", ".webp"}
_SINGLE_FILE_EXT = {".pptx", ".potx", ".pptm"} | _IMAGE_EXT

StepCallback = Callable[..., None]  # (что, итог) или (что, итог, часть) — см. `StepReporter`


def brand_steps(spec: BrandSpec) -> list[tuple[str, str]]:
    """Шаги разбора словами — для ленты «Разбираю брендбук…»: (что, итог)."""
    texts = step_texts(spec)
    return [texts[k] for k in STEP_KEYS]


def brand_partials(spec: BrandSpec) -> list[dict]:
    """Прочитанное каждым шагом (в порядке `brand_steps`): то, что клиент склеивает в плитки анализа."""
    parts = step_partials(spec)
    return [parts[k] for k in STEP_KEYS]


def read_brandbook(source: Path | str, *, providers: Any = None, skills: Any = None, use_vlm: bool = False,
                   assets_dir: Optional[Path | str] = None, on_step: Optional[StepCallback] = None,
                   figma_token: Optional[str] = None, figma_client: Any = None) -> BrandSpec:
    """Брендбук (файл, папка, архив или ссылка Figma) → `BrandSpec`.

    `use_vlm` — PDF уточняется моделью (`providers` с ролью vlm, `skills` — реестр навыков; без них — чтение по тексту).
    `assets_dir` — куда сложить логотипы (из PDF, папки или архива); пути в `BrandSpec.logos` — относительно неё.
    `figma_token` / `figma_client` — для ссылок Figma (по умолчанию `FIGMA_TOKEN` из окружения и настоящий HTTP).

    `on_step(что, итог)` или `on_step(что, итог, часть)` — ход чтения (обработчик с двумя аргументами работает как раньше). Шаги
    «открыт файл», «палитра», «шрифты», «логотипы», «правила» приходят по мере чтения, а не после него: у PDF — сразу, как готов
    разбор по тексту, до запроса к модели (он идёт до двух минут), затем «страница N из M» и «модель читает …», а шаги, которые
    модель уточнила, повторяются с новым итогом. Остальные источники читаются быстро и говорят шаги подряд в конце, перед
    возвратом. `часть` — прочитанное шагом (`brand_partials`); у «страница» и «модель» её нет (None). Каждый шаг приходит до
    возврата `read_brandbook`, поэтому звать `brand_steps(spec)` ещё раз после чтения не нужно."""
    rep = StepReporter(on_step)
    progress = rep.progress if rep.cb is not None else None
    kw = dict(providers=providers, skills=skills, use_vlm=use_vlm, assets_dir=assets_dir)
    figma_url = normalize_url(source) if isinstance(source, str) else None
    if figma_url is None and isinstance(source, str) and re.match(r"^\s*[a-z][a-z0-9+.-]*://", source, re.I):
        raise BrandReadError("По ссылке читаю только файлы Figma. Другой брендбук загрузите файлом: PDF, JSON с токенами, "
                             "папку или ZIP с логотипами и примерами слайдов.")
    if figma_url is not None and not Path(source).exists():
        spec = read_figma_url(figma_url, token=figma_token, client=figma_client)
    else:
        path = Path(source)
        if not path.exists():
            raise BrandReadError(f"Не нашёл «{path.name}» — проверьте путь к брендбуку.")
        if path.is_dir():
            spec = read_folder(path, on_progress=progress, **kw)
        else:
            ext = path.suffix.lower()
            if ext == ".fig":
                raise BrandReadError(FIG_FILE)
            if path.stat().st_size == 0:
                raise BrandReadError(f"Файл «{path.name}» пустой.")
            if ext == ".json":
                spec = read_tokens(path)
            elif ext == ".pdf":
                spec = read_pdf(path, on_step=rep, **kw)
            elif ext == ".zip":
                spec = read_zip(path, on_progress=progress, **kw)
            elif ext in _SINGLE_FILE_EXT:
                spec = read_collection([path], path.parent, label=path.name, guess_name=ext not in _IMAGE_EXT, on_progress=progress, **kw)
            else:
                raise BrandReadError(f"Формат «{ext or path.name}» для брендбука не подходит. Подойдут: {SUPPORTED}.")
    if not spec.colors and not spec.fonts and not spec.logos:
        raise BrandReadError("Не нашёл в брендбуке ни цветов, ни шрифтов, ни логотипов — проверьте файл.")
    pdf_without_store = spec.source == "pdf" and assets_dir is None  # логотипы PDF некуда было сложить — не знаем
    if not spec.logos and not pdf_without_store and NO_LOGO_FILES not in spec.warnings:
        # (токены говорят «логотип — справа внизу», но файлов нет: человек должен это увидеть в слое «Брендбук»)
        spec.warnings.append(NO_LOGO_FILES)
    rep.finish(spec)  # шаги, которые чтение ещё не сказало (у PDF все уже сказаны по ходу)
    return spec
