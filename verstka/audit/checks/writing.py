"""The words a deck shows (gate 4, G4-13 and G4-21): a line cut out of its sentence, a clock time or a project number
shown as a key figure, a chart of two different quantities, a heading used twice, a stand-alone line that opens with
«Также» or «они», and a topic deck whose text was never written.

A deck the agent wrote from a topic (writer mode) keeps the writer's sentences in each slide's speaker notes; the first
slide's notes say «Текст написан агентом Verstka…» (planning/writer.py `attribution`), or the generation passes the
writer's record (`AuditContext.writer`). The notes are the source a slide's lines are read against:

- line_fragment: a line (a bullet, a card, a paragraph, the conclusion) that is a piece of one source sentence and
  lost what makes it a statement — it has no predicate while the dropped part has one («6 июня 1944 года союзные силы
  США» of «…союзные силы США, Великобритании и Канады … провели … и высадились в Нормандии»), it stops before the
  sentence's «, но …» or the «как …» its «такими» asks for («ТДУ … проработала успешно» of «…успешно, но отключилась
  на секунду раньше»), or it ends on a word that governs what was cut («…произошло только», «…28,6 ГВт, из них»);
- figure_is_time: a key figure whose number the source writes only as a clock time («в 10 часов 53 минуты» shown as
  «10 ч») or as a code («ледоколы проекта 22220», «Ту-144»);
- orphan_opener: a stand-alone line that opens with a connector or an anaphora that points outside it («Также
  компания…», «В том же году…», «Они предложили…», «Вдохновлённые …, они…»), a key figure's label with a pronoun
  («государства в ней»), a possessive with no name before it on the line or in the heading («…был и её первый
  министр»).

Every deck:

- duplicate_heading: two slides with the same heading;
- chart_mixed_units: one chart series whose values the source counts in different units or things («36 энергоблоков»
  and «в 54 страны» as two columns of one chart);
- writer_failed (error): a topic deck whose writer failed or declined, so that its content slides are only section
  dividers — never a score of 100 for a deck with no text.

No model call. The checks are warnings (writer_failed an error); each names the lines it read on the slide."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from verstka.audit.checks.common import title_element
from verstka.audit.registry import AuditContext, check
from verstka.schemas.audit import CheckSpec, Issue
from verstka.schemas.deck_ir import IRSlide
from verstka.schemas.outline import OutlineSlide

LINE_FRAGMENT = CheckSpec(
    id="line_fragment",
    title="Строка — обрывок предложения",
    severity="warn",
    category="content",
    description=(
        "Текст, написанный агентом по теме: строка слайда (пункт, карточка, абзац, вывод) — кусок предложения из текста "
        "слайда в заметках, который потерял смысл: начало предложения без сказуемого, оставшегося в отброшенной части "
        "(«6 июня 1944 года союзные силы США»), или обстоятельство без своего предложения («С Юрием Гагариным на борту»); "
        "строка остановлена перед «, но …» или перед «как …», которого требует «такими» («ТДУ проработала успешно» без "
        "«но отключилась раньше»); строка кончается служебным словом — предлогом, союзом, частицей, «из них» "
        "(«Выключение двигателя произошло только»). Пункт перечисления из предложения и событие под своей датой — "
        "нормальные строки."
    ),
)
FIGURE_IS_TIME = CheckSpec(
    id="figure_is_time",
    title="Ключевое число — время суток или номер",
    severity="warn",
    category="content",
    description=(
        "Текст, написанный агентом по теме: число крупной цифры слайда встречается в тексте слайда только как время "
        "суток («в 10 часов 53 минуты», «в 9:07») или как номер — проекта, модели, серии, рейса, «Ту-144», «Восток-1» "
        "(«ледоколы проекта 22220»). На слайде оно выглядит величиной («10 ч», «22220»), которой в тексте нет."
    ),
)
ORPHAN_OPENER = CheckSpec(
    id="orphan_opener",
    title="Строка начинается со ссылки на то, чего на слайде нет",
    severity="warn",
    category="content",
    description=(
        "Текст, написанный агентом по теме: пункт, карточка или подпись стоят на слайде отдельно, но начинаются со "
        "связки или отсылки к предыдущему предложению — «Также…», «Кроме того…», «При этом…», «В том же году…», "
        "«Этот…», «Она…», «Они…», «Его…» (в том числе после оборота: «Вдохновлённые …, они предложили…»); подпись "
        "крупной цифры с местоимением («государства в ней»); притяжательное «её/его/их», перед которым ни в строке, ни в "
        "заголовке нет имени («…был и её первый министр»)."
    ),
)
DUPLICATE_HEADING = CheckSpec(
    id="duplicate_heading",
    title="Два слайда с одинаковым заголовком",
    severity="warn",
    category="content",
    description=(
        "Заголовок слайда повторяет заголовок другого слайда колоды (без учёта регистра, пробелов и знаков препинания). "
        "Титульный и финальный слайды не сравниваются; «… (продолжение)» — другой заголовок."
    ),
)
CHART_MIXED_UNITS = CheckSpec(
    id="chart_mixed_units",
    title="На диаграмме смешаны разные величины",
    severity="warn",
    category="content",
    description=(
        "Значения одного ряда диаграммы в исходном тексте относятся к разным величинам: после числа стоят разные "
        "единицы или разные предметы счёта («36 энергоблоков» и «в 54 страны» — два столбца одной диаграммы). Число "
        "ищется в тексте слайда в заметках и в исходном тексте, в предложении со словами подписи категории; "
        "проверяются ряды, у которых единица найдена хотя бы у двух значений."
    ),
)
WRITER_FAILED = CheckSpec(
    id="writer_failed",
    title="Текст по теме не написан",
    severity="error",
    category="integrity",
    description=(
        "Презентация по теме без материалов: агент не написал текст (модель недоступна, отказалась писать или тема — "
        "частное лицо), и все содержательные слайды — только разделители разделов. Такая презентация не может "
        "получить 100 баллов: на результате видно, что текста нет."
    ),
)

WRITTEN_MARK = "Текст написан агентом"  # planning/writer.py ATTRIBUTION_PREFIX («Текст написан агентом Verstka …»)
MIN_CUT_WORDS = 4  # a verbless cut shorter than this is a label («Посадка корабля»), not a broken sentence
MAX_LABEL_WORDS = 8  # a key figure's label read for pronouns

# ------------------------------------------------------------------ words

_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+(?:[-‐‑][0-9A-Za-zА-Яа-яЁё]+)*")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+(?=[«\"„(\[]?[А-ЯЁA-Z0-9])")
_WS_RE = re.compile(r"[\s    ⁠]+")


def _norm(w: str) -> str:
    return w.lower().replace("ё", "е").replace("‐", "-").replace("‑", "-")


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").replace("⁠", "")).strip()


def tokens(text: str) -> list[tuple[str, int, int]]:
    """(normalized word, start, end) of every word and number of the text («Восток-1» and «военно-политических» one
    word each; «28,6» two numbers)."""
    return [(_norm(m.group(0)), m.start(), m.end()) for m in _TOKEN_RE.finditer(text or "")]


def sentences(text: str) -> list[str]:
    """The sentences of a slide's notes (the writer's text of the slide); the attribution line is not one."""
    out = []
    for para in re.split(r"\n+", text or ""):
        para = _clean(para)
        if not para or WRITTEN_MARK in para:
            continue
        out.extend(s.strip() for s in _SENT_SPLIT_RE.split(para) if s.strip())
    return out


# a finite verb, as a detector that errs towards «yes» (a line's own predicate must never be missed) and one that
# errs towards «no» (the predicate of the dropped part: a noun read as a verb there would call a label a fragment)
_VERB_WORDS = frozenset(
    """был была было были будет будут есть стал стала стало стали мог могла могло могли смог смогла смогли помог
    помогла помогли рос вырос выросла выросло выросли погиб погибла погибли достиг достигла достигли умер умерла умерли
    шел шла шло шли пришел пришла пришли вошел вошла вошли ушел ушла ушли нашел нашла нашли прошел прошла прошли
    произошел произошла произошло произошли перешел перешла перешли вышел вышла вышли превзошел превзошла лег легла легли
    привез привезла привезли принес принесла принесли вез везла везли нес несла несли сжег сожгли испек испекли
    является являются стоит стоят идет идут дает дают""".split()
)
_STRICT_VERB_RE = re.compile(
    r"(?:"
    r"(?:ает|яет|еет|ует|ают|яют|еют|уют|ется|ится|ются|ятся|утся|атся)"  # развивает, владеет, действует, считается
    r"|(?:[аеиоуыяэ]л|[гкзсшбпт]л)(?:ся|ась|ось|ись|сь)"  # высадился, завершилась, вторглась, занимались
    r"|[аеиоуыяэ]л[аои]?"  # начал, подписала, провели, произошло (after the noun stoplist)
    r")$"
)
_LOOSE_VERB_RE = re.compile(
    r"(?:"
    r"(?:ет|ёт|ит|ут|ют|ат|ят)(?:ся)?"  # говорит, строят, идут
    r"|л[аои]?(?:сь|ся)?"  # any past form: пришла, погибли, росло
    r"|(?:ан|ен|ён|ят|ыт|ит|ут)[аоы]?"  # short participles as the predicate: основана, запущен, открыт, разведано
    r"|[бвгджзклмпрстфхцчшщ]н[аоы]|(?:ов|ив|им|ем)[аоы]"  # short adjectives: недоступна, нужны, готова, необходимо
    r")$"
)
# nouns with a verb's ending (the strict detector's stoplist, by stem: «урала», «маршалы», «модели», «начало»)
_NOUN_STEMS = frozenset(
    """материал капитал канал финал журнал сигнал терминал персонал потенциал идеал сериал портал интервал арсенал
    скандал ритуал минерал генерал адмирал маршал вокзал зал бал пенал урал непал стол пол гол футбол протокол престол
    символ глагол посол укол отдел предел раздел удел пробел крокодил нил тыл пыл стул гул аул кол ствол орел котел
    цел рол модел недел автомобил мысл угл рубл корол дол бол сол вол школ сил пчел игл дел тел сел нача правил числ
    масл весл ремесл стекл крыл мыл зеркал кресл одеял покрывал шил сал кол анжел паол бенилюкс мал бал мил""".split()
)
_NOUN_SUFFIXES = ("ители", "атели", "ятели", "ителей", "ителя", "ателя")


def _verb_stem(w: str) -> str:
    return re.sub(r"(?:ами|ями|ах|ях|ов|ей|ом|ем|ой|ою|ам|ям|а|я|о|е|и|ы|у|ю)$", "", w)


def strict_verb(word: str) -> bool:
    w = _norm(word)
    if len(w) < 3 or not re.fullmatch(r"[а-я-]+", w):
        return False
    if w in _VERB_WORDS:
        return True
    if w.endswith(_NOUN_SUFFIXES) or w in _NOUN_STEMS or _verb_stem(w) in _NOUN_STEMS:
        return False
    return len(w) >= 4 and bool(_STRICT_VERB_RE.search(w))


def loose_verb(word: str) -> bool:
    w = _norm(word)
    if len(w) < 3 or not re.fullmatch(r"[а-я-]+", w):
        return False
    return w in _VERB_WORDS or strict_verb(w) or (len(w) >= 4 and bool(_LOOSE_VERB_RE.search(w)))


_DASH_PRED_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё»)%₽]\s+[—–]\s+[0-9A-Za-zА-Яа-яЁё«(]")


def has_predicate(text: str, strict: bool = False) -> bool:
    """A finite verb, a short participle (loose) or a dash for the verb («Россия — четвёртая …»)."""
    if _DASH_PRED_RE.search(text or ""):
        return True
    test = strict_verb if strict else loose_verb
    return any(test(w) for w, _, _ in tokens(text))


# the words a cut line may not end on: they govern what was cut (a preposition, a conjunction, a particle)
_END_WORDS = frozenset(
    """в во на с со к ко по о об обо от до из у за для при без через над под про между среди перед и а но или либо
    чтобы если хотя однако причем притом только лишь даже не ни который которая которое которые которых которым
    которой котором которого которую чей чья чье чьи""".split()
)
_END_QUESTION = frozenset("что как где когда куда откуда чем".split())  # a question heading may end on them
_END_PAIRS = frozenset({
    ("из", "них"), ("из", "которых"), ("среди", "них"), ("том", "числе"), ("такие", "как"), ("таких", "как"),
    ("такими", "как"), ("такой", "как"), ("такая", "как"), ("такое", "как"), ("так", "и"), ("а", "также"),
    ("в", "частности"), ("то", "есть"), ("в", "том"),
})
_PREPOSITIONS = frozenset("в во на с со к ко по о об обо от до из у за для при без через над под про между среди перед после вокруг около".split())
# what the dropped rest must not be: a turn that changes the kept half («…успешно, но отключилась раньше», «…, а не …»);
# a plain «, а другая …» / «, а напиток …» only adds a clause
_CONTRAST_AFTER_RE = re.compile(r"^\s*[,;]?\s*(?:но|однако|хотя|зато|а\s+не)(?![0-9A-Za-zА-Яа-яЁё])", re.I)
_AS_AFTER_RE = re.compile(r"^\s*,?\s*как(?![0-9A-Za-zА-Яа-яЁё])", re.I)
_SUCH_RE = re.compile(r"^так(?:ой|ая|ое|ие|их|им|ими|ую|ом|ого|ому|ов)?$")


def ends_on_governing_word(text: str, heading: bool = False) -> Optional[str]:
    """The governing word a line ends on («только», «из них»), None when it ends on a word of its own."""
    raw = (text or "").rstrip()
    if raw.endswith(("…", "...")) or raw.endswith("?"):
        return None  # an ellipsis or a question is the author's choice, not a cut
    toks = [w for w, _, _ in tokens(raw)]
    if len(toks) < 2:
        return None
    if (toks[-2], toks[-1]) in _END_PAIRS:
        return f"{toks[-2]} {toks[-1]}"
    last = toks[-1]
    if last in _END_WORDS or (not heading and last in _END_QUESTION):
        return last
    return None


# ------------------------------------------------------------------ a deck written by the agent


def writer_status(writer: Any) -> Optional[str]:
    """The writer's status from what the generation passed: its summary (dict), its result (an object with .status)
    or the status itself."""
    if writer is None:
        return None
    if isinstance(writer, str):
        return writer
    if isinstance(writer, dict):
        s = writer.get("status")
        return str(s) if s else None
    s = getattr(writer, "status", None)
    return str(s) if s else None


def written_deck(ctx: AuditContext) -> bool:
    """The deck shows text the agent wrote from a topic (its first slide's notes carry the attribution line)."""
    if writer_status(getattr(ctx, "writer", None)) == "written":
        return True
    if ctx.ir.slides and WRITTEN_MARK in (ctx.ir.slides[0].notes or ""):
        return True
    o = ctx.outline
    return bool(o is not None and o.slides and WRITTEN_MARK in (o.slides[0].notes or ""))


def _outline_slide(ctx: AuditContext, s: IRSlide) -> Optional[OutlineSlide]:
    if ctx.outline is None or not s.outline_id:
        return None
    return next((o for o in ctx.outline.slides if o.id == s.outline_id), None)


def _kind(osl: OutlineSlide) -> str:
    return osl.kind.value if hasattr(osl.kind, "value") else str(osl.kind)


@dataclass
class Line:
    """A line the slide shows on its own: `role` heading | bullet | card | card_text | label | paragraph | takeaway."""

    role: str
    text: str
    value: str = ""  # a key figure's value (role label)
    titled: bool = False  # a card's text under a title of its own (not a date)
    title: str = ""  # a card of a title and a text: its title (the line is «title text», as one sentence may say it)
    dated: bool = False  # a timeline entry's text under its date


_MONTH_RE = re.compile(r"^(?:январ|феврал|март|апрел|ма[йяе]$|июн|июл|август|сентябр|октябр|ноябр|декабр|весн|лет[оа]$|осен|зим)")
_DATE_WORDS = frozenset("и по с до год года году годы годов гг г конец конца начало начала середина середины середине квартал кв".split())


def _date_only(text: str) -> bool:
    """A date and nothing else: «1606 год», «6 и 9 августа 1945», «Июнь — июль 1941», «1990-е», «Q3 2025»."""
    toks = [w for w, _, _ in tokens(text)]
    if not toks or not any(w[:1].isdigit() or re.fullmatch(r"q[1-4]", w) for w in toks):
        return False
    return all(w.isdigit() or re.fullmatch(r"\d{3,4}-е|\d{1,2}-[а-я]{1,2}|q[1-4]", w) or _MONTH_RE.match(w) or w in _DATE_WORDS for w in toks)


def slide_lines(osl: OutlineSlide) -> list[Line]:
    """Every line the plan puts on the slide, as the reader meets it."""
    c = osl.content
    out: list[Line] = []
    if (osl.headline or "").strip():
        out.append(Line("heading", _clean(osl.headline)))
    out.extend(Line("bullet", _clean(b)) for b in c.bullets if (b or "").strip())
    out.extend(Line("paragraph", _clean(p)) for p in c.paragraphs if (p or "").strip())
    for it in [*c.items, *c.columns]:
        title, text = _clean(it.title), _clean(it.text)
        dated = _date_only(title)
        if title and text and not dated:
            out.append(Line("card", f"{title} {text}", title=title))
            out.append(Line("card_text", text, titled=True))
        elif title and not dated:
            out.append(Line("card", title))
        elif text:
            out.append(Line("card_text", text, dated=dated))
        out.extend(Line("bullet", _clean(b)) for b in it.bullets if (b or "").strip())
    for n in c.numbers:
        if (n.label or "").strip():
            out.append(Line("label", _clean(n.label), value=_clean(n.value)))
    if (osl.takeaway or "").strip():
        out.append(Line("takeaway", _clean(osl.takeaway)))
    return out


def _bbox_of(s: IRSlide, text: str) -> tuple[list, list]:
    """The box of the slide's text element that shows the line (for the remark's place), else nothing."""
    key = "".join(w for w, _, _ in tokens(text))[:24]
    if not key:
        return [], []
    for e in s.elements:
        if e.type == "text" and e.has_text and key in "".join(w for w, _, _ in tokens(e.text)):
            return [e.bbox_frac], [e.id]
    return [], []


def _quoted(texts: Iterable[str], n: int = 3, width: int = 60) -> str:
    items = [t if len(t) <= width else t[: width - 1].rstrip() + "…" for t in texts]
    return ", ".join(f"«{t}»" for t in items[:n]) + ("…" if len(items) > n else "")


# ------------------------------------------------------------------ line_fragment


@dataclass
class _Cut:
    sentence: str
    start: int
    end: int
    first: int
    last: int  # token index after the line's last word


def find_in_sentences(text: str, sents: list[str]) -> Optional[_Cut]:
    """Where the line's words stand in one sentence of the source, word for word (case, «ё», punctuation aside)."""
    want = [w for w, _, _ in tokens(text)]
    n = len(want)
    if not n:
        return None
    for s in sents:
        st = tokens(s)
        words = [w for w, _, _ in st]
        for j in range(0, len(words) - n + 1):
            if words[j : j + n] == want:
                return _Cut(s, st[j][1], st[j + n - 1][2], j, j + n)
    return None


def fragment_reason(line: Line, sents: list[str]) -> Optional[str]:
    """Why the line is a broken piece of its sentence, None when it reads on its own."""
    gov = ends_on_governing_word(line.text, heading=line.role == "heading")
    if gov:
        return f"кончается на «{gov}»"
    if line.role == "label":
        return None
    cut = find_in_sentences(line.text, sents)
    if cut is None:
        if line.title and line.title != line.text:
            # the card's title alone, read as the card's heading (a noun phrase is a proper title; a title that
            # stops before «, но …» or ends on «только» is not)
            return fragment_reason(Line("heading", line.title), sents)
        return None
    total = len(tokens(cut.sentence))
    before, after = cut.sentence[: cut.start], cut.sentence[cut.end :]
    if cut.first == 0 and cut.last == total:
        return None  # the whole sentence
    rest_words = len(tokens(before)) + len(tokens(after))
    if _CONTRAST_AFTER_RE.match(after) and len(tokens(after)) >= 2:
        return f"без продолжения предложения «{_short(after.lstrip(' ,;'))}» — смысл меняется"
    if _AS_AFTER_RE.match(after) and any(_SUCH_RE.match(w) for w, _, _ in tokens(line.text)):
        return f"«такими …» без «{_short(after.lstrip(' ,;'))}»"
    if line.role == "heading" or (line.role == "card_text" and (line.titled or line.dated)):
        return None  # a heading, a card's explanation under its title, a timeline entry may be a noun phrase
    span = cut.sentence[cut.start : cut.end]
    if len(tokens(line.text)) < MIN_CUT_WORDS or rest_words < 2 or has_predicate(span) or not has_predicate(f"{before} … {after}", strict=True):
        return None
    if cut.first == 0:
        # the sentence's start — its subject, its date — without the predicate: «6 июня 1944 года союзные силы США»
        return "нет сказуемого: оно осталось в отброшенной части предложения"
    if tokens(line.text)[0][0] in _PREPOSITIONS:
        # a circumstance torn off its clause: «С Юрием Гагариным на борту», «После атомных бомбардировок …»
        return "это обстоятельство без предложения, к которому оно относится"
    return None  # an item of the sentence's enumeration («Агрессивная политика Германии») is a proper list line


def _short(text: str, n: int = 50) -> str:
    t = _clean(text).rstrip(".")
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def _sources(ctx: AuditContext, s: IRSlide, osl: Optional[OutlineSlide]) -> list[str]:
    """The slide's source sentences: its notes (the writer's text of the slide), else the brief's."""
    got = sentences((osl.notes if osl is not None and osl.notes else s.notes) or "")
    if not got and ctx.brief_text:
        got = sentences(ctx.brief_text)
    return got


@check(LINE_FRAGMENT)
def line_fragment(ctx: AuditContext) -> list[Issue]:
    if not written_deck(ctx):
        return []
    out: list[Issue] = []
    for s in ctx.ir.slides:
        osl = _outline_slide(ctx, s)
        if osl is None or _kind(osl) in ("title", "section", "thanks", "agenda"):
            continue
        sents = _sources(ctx, s, osl)
        found: list[tuple[Line, str]] = []
        for ln in slide_lines(osl):
            if ln.role == "card_text" and ln.titled and any(f.text.endswith(ln.text) for f, _ in found):
                continue
            why = fragment_reason(ln, sents)
            if why and all(ln.text != f.text for f, _ in found):
                found.append((ln, why))
        if not found:
            continue
        first, why = found[0]
        boxes, ids = _bbox_of(s, first.text)
        more = f" (и ещё {len(found) - 1})" if len(found) > 1 else ""
        out.append(ctx.new_issue(LINE_FRAGMENT, s.index, f"строка «{_short(first.text, 70)}» — обрывок предложения: {why}{more}", bboxes=boxes, element_ids=ids, details={"lines": [{"text": ln.text, "role": ln.role, "why": w} for ln, w in found]}))
    return out


# ------------------------------------------------------------------ figure_is_time

_NUM_RE = re.compile(r"(?<![\d,.])\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?(?!\d)|(?<![\d,.])\d+(?:[.,]\d+)?(?![\d])")
_TIME_AFTER_RE = re.compile(
    r"^(?::\d{2}(?!\d)"  # 10:53
    r"|\.\d{2}\s*(?:по\s+москов|мск|утра|вечера|дня|ночи)"  # 10.53 по московскому
    r"|\s*(?:ч\.?|час(?:а|ов)?)\s*\d{1,2}\s*(?:мин(?:ут[аы]?|\.)?)(?![а-яё])"  # 10 часов 53 минуты, 9 ч 07 мин
    r"|\s*час(?:а|ов)?\s+(?:утра|вечера|дня|ночи|по\s+москов))",  # в 10 часов утра
    re.I,
)
_CODE_BEFORE_RE = re.compile(
    r"(?:проект\w*|модел\w*|сери[яиюй]\w*|номер\w*|№|код\w*|тип[ауе]?|индекс\w*|артикул\w*|рейс\w*|борт\w*|шифр\w*|"
    r"верси[яиюй]\w*|марк[аиуе]\w*|класс\w*|гост\w*|стандарт\w*|заказ\w*|позывн\w*)\s*$"
    r"|[A-Za-zА-Яа-яЁё]{1,12}[-‐‑]\s*$",  # Ту-144, Восток-1, Р-7
    re.I,
)


def _num_key(t: str) -> str:
    return re.sub(r"[   ]", "", t).replace(",", ".")


def figure_source_kind(value: str, sents: list[str]) -> Optional[tuple[str, str]]:
    """(«time» | «code», the source's phrase) when every place the source writes the key figure's number is a clock
    time or a code; None when the number is a quantity somewhere (or is not in the source)."""
    v = _clean(value)
    if ":" in v:
        return None  # a clock time shown as a time
    m = _NUM_RE.search(v)
    if not m:
        return None
    key = _num_key(m.group(0))
    seen: list[tuple[str, str]] = []
    for s in sents:
        for n in _NUM_RE.finditer(s):
            if _num_key(n.group(0)) != key:
                continue
            before, after = s[: n.start()], s[n.end() :]
            phrase = _clean(s[max(0, n.start() - 30) : n.end() + 25])
            if _TIME_AFTER_RE.match(after):
                seen.append(("time", phrase))
            elif _CODE_BEFORE_RE.search(before[-30:]):
                seen.append(("code", phrase))
            else:
                return None
    if not seen:
        return None
    kind = "time" if any(k == "time" for k, _ in seen) else "code"
    return kind, next(p for k, p in seen if k == kind)


@check(FIGURE_IS_TIME)
def figure_is_time(ctx: AuditContext) -> list[Issue]:
    if not written_deck(ctx):
        return []
    out: list[Issue] = []
    for s in ctx.ir.slides:
        osl = _outline_slide(ctx, s)
        if osl is None:
            continue
        sents = _sources(ctx, s, osl)
        values = [n.value for n in osl.content.numbers] + [it.number for it in osl.content.items if it.number]
        for v in values:
            got = figure_source_kind(v or "", sents)
            if got is None:
                continue
            kind, phrase = got
            what = "время суток" if kind == "time" else "номер (проекта, модели, серии)"
            boxes, ids = _bbox_of(s, v)
            out.append(ctx.new_issue(FIGURE_IS_TIME, s.index, f"крупное число «{_clean(v)}» — в тексте это {what}: «…{_short(phrase, 60)}…», а не величина", bboxes=boxes, element_ids=ids, details={"value": v, "kind": kind, "source": phrase}))
    return out


# ------------------------------------------------------------------ orphan_opener

_CONNECTOR_RE = re.compile(
    r"^(?:также|тоже|кроме\s+того|помимо\s+(?:этого|того)|при\s+этом|однако|поэтому|тем\s+не\s+менее|более\s+того|"
    r"вместе\s+с\s+тем|в\s+то\s+же\s+время|впоследствии|после\s+этого|в\s+результате\s+этого|в\s+связи\s+с\s+этим|"
    r"в\s+(?:том|этом)\s+же\s+(?:году|месяце|веке|десятилетии)|в\s+тот\s+же\s+(?:день|год|месяц|период)|тогда\s+же|"
    r"там\s+же|к\s+тому\s+времени|этот|эта|это|эти|этого|этой|этом|этим|этих|эту)(?![0-9A-Za-zА-Яа-яЁё])",
    re.I,
)
_PRONOUN_START_RE = re.compile(r"^(?:он|она|оно|они|его|её|ее|их|ему|ей|им)(?![0-9A-Za-zА-Яа-яЁё])", re.I)
_PRONOUN_AFTER_PHRASE_RE = re.compile(r"^([^,.;:—–]{3,90}),\s+(он|она|оно|они)(?![0-9A-Za-zА-Яа-яЁё])", re.I)
_LABEL_PRONOUN_RE = re.compile(r"(?<![0-9A-Za-zА-Яа-яЁё])(?:он|она|оно|они|его|её|ее|их|ему|ей|им|ней|нём|нем|них|ним|ними|нему|неё|нее)(?![0-9A-Za-zА-Яа-яЁё])", re.I)
_POSSESSIVE_RE = re.compile(r"(?<![0-9A-Za-zА-Яа-яЁё])(её|ее|его|их)\s+[а-яё]", re.I)
_LEAD_FIGURE_RE = re.compile(r"^[^—–:]{0,40}?\d[^—–:]{0,30}?\s[—–:]\s+")  # «2012 — …», «22 июня 1941 — …», «62 — …»
_ADJ_END_RE = re.compile(r"(?:ым|им|ой|ей|ая|яя|ое|ее|ые|ие|ых|их|ом|ем|ую|юю|ого|его|ому|ему)$")
_FUNCTION_WORDS = frozenset("в во на с со к по о от до из у за для при после перед когда если как так но и а однако также".split())


def _has_name(text: str, skip_first: bool) -> bool:
    """A word that can stand for a pronoun's name: a capitalized or Latin word (the first word only when it is not an
    adjective, an adverb or a function word)."""
    for k, m in enumerate(_TOKEN_RE.finditer(text)):
        w = m.group(0)
        if re.match(r"[A-Za-z]", w) and k > 0:
            return True
        if not w[:1].isupper():
            continue
        if k == 0:
            lw = _norm(w)
            if skip_first or lw in _FUNCTION_WORDS or _ADJ_END_RE.search(lw) or loose_verb(lw):
                continue
        return True
    return False


def orphan_reason(line: Line, heading: str) -> Optional[str]:
    """Why a stand-alone line reads as the middle of a text, None when it stands on its own."""
    t = _clean(line.text)
    if line.role == "label":
        m = _LABEL_PRONOUN_RE.search(t)
        if m and len(tokens(t)) <= MAX_LABEL_WORDS:
            return f"подпись числа с местоимением «{m.group(0)}»"
        return None
    t = _LEAD_FIGURE_RE.sub("", t, count=1) if line.role != "heading" else t
    m = _CONNECTOR_RE.match(t)
    if m:
        return f"начинается с «{m.group(0)}»"
    if not (line.role == "card_text" and line.titled):
        m = _PRONOUN_START_RE.match(t)
        if m:
            return f"начинается с «{m.group(0)}»"
        m = _PRONOUN_AFTER_PHRASE_RE.match(t)
        if m and not has_predicate(m.group(1)):  # «Вдохновлённые покупкой Hotmail, они…»: the phrase describes «они»
            return f"«{m.group(2)}» после оборота «{_short(m.group(1), 40)}» — не сказано, кто"
    if line.role in ("bullet", "card", "paragraph", "takeaway"):
        m = _POSSESSIVE_RE.search(t)
        if m and m.start() > 0 and not _has_name(t[: m.start()], skip_first=False) and not _has_name(heading, skip_first=True):
            return f"«{m.group(1)}» — не сказано, чей"
    return None


@check(ORPHAN_OPENER)
def orphan_opener(ctx: AuditContext) -> list[Issue]:
    if not written_deck(ctx):
        return []
    out: list[Issue] = []
    for s in ctx.ir.slides:
        osl = _outline_slide(ctx, s)
        if osl is None or _kind(osl) in ("title", "section", "thanks", "agenda"):
            continue
        heading = _clean(osl.headline)
        found: list[tuple[Line, str]] = []
        for ln in slide_lines(osl):
            why = orphan_reason(ln, heading)
            if why and all(ln.text != f.text and not f.text.endswith(ln.text) and not ln.text.endswith(f.text) for f, _ in found):
                found.append((ln, why))
        if not found:
            continue
        first, why = found[0]
        shown = f"{first.value} — {first.text}" if first.role == "label" and first.value else first.text
        boxes, ids = _bbox_of(s, first.text)
        more = f" (и ещё {len(found) - 1})" if len(found) > 1 else ""
        out.append(ctx.new_issue(ORPHAN_OPENER, s.index, f"строка «{_short(shown, 70)}» {why}{more}: на слайде она стоит отдельно", bboxes=boxes, element_ids=ids, details={"lines": [{"text": ln.text, "role": ln.role, "why": w} for ln, w in found]}))
    return out


# ------------------------------------------------------------------ duplicate_heading


def _heading_key(text: str) -> str:
    return " ".join(w for w, _, _ in tokens(text))


@check(DUPLICATE_HEADING)
def duplicate_heading(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    seen: dict[str, int] = {}
    for s in ctx.ir.slides:
        osl = _outline_slide(ctx, s)
        if osl is not None:
            if _kind(osl) in ("title", "thanks"):
                continue
            head = osl.headline or ""
        else:
            if ctx.outline is not None or s.index in (1, len(ctx.ir.slides)):
                continue
            te = title_element(s)
            head = te.text if te is not None else ""
        key = _heading_key(head)
        if len(key) < 4:
            continue
        other = seen.get(key)
        if other is None:
            seen[key] = s.index
            continue
        te = title_element(s)
        out.append(ctx.new_issue(DUPLICATE_HEADING, s.index, f"заголовок «{_short(head, 70)}» уже был на слайде {other}", bboxes=[te.bbox_frac] if te is not None else [], element_ids=[te.id] if te is not None else [], details={"other": other, "heading": _clean(head)}))
    return out


# ------------------------------------------------------------------ chart_mixed_units

_SCALE_RE = re.compile(r"^(?:тыс\.?|тысяч\w*|млн\.?|миллион\w*|млрд\.?|миллиард\w*|трлн\.?|триллион\w*)$", re.I)
_UNIT_STOP = frozenset(
    """и в во на по а или за до от к у с со из при для как что это год года году годах лет""".split()
)
_UNIT_ALIASES = (
    (re.compile(r"^(?:%|процент\w*|п\.?п\.?)$", re.I), "%"),
    (re.compile(r"^(?:₽|руб\w*|р\.?)$", re.I), "₽"),
    (re.compile(r"^(?:\$|долл\w*|usd)$", re.I), "$"),
    (re.compile(r"^(?:€|евро|eur)$", re.I), "€"),
    (re.compile(r"^(?:шт\.?|штук\w*)$", re.I), "шт"),
    (re.compile(r"^(?:чел\.?|человек\w*)$", re.I), "чел"),
)
_AFTER_NUM_RE = re.compile(r"^\s*(%|₽|\$|€|[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё.\-]*)")


def unit_after(text_after: str) -> Optional[str]:
    """The unit or counted thing written right after a number («энергоблоков» → «энерг», «%», «₽»), scale words
    skipped; None when the number is followed by nothing that counts."""
    rest = text_after
    for _ in range(3):
        m = _AFTER_NUM_RE.match(rest)
        if not m:
            return None
        w = m.group(1)
        if _SCALE_RE.match(w) or _SCALE_RE.match(w.rstrip(".")):
            rest = rest[m.end() :]
            continue
        lw = _norm(w).rstrip(".")
        for rx, name in _UNIT_ALIASES:
            if rx.match(lw) or rx.match(w):
                return name
        if lw in _UNIT_STOP or len(lw) < 3 or not re.fullmatch(r"[а-яa-z-]+", lw) or strict_verb(lw):
            return None
        return lw[:5]
    return None


def _num_forms(v: float) -> set[str]:
    """How a text may write a chart value: 36, 36,0, 18,6, 1 200 000."""
    out = set()
    if abs(v - round(v)) < 1e-9:
        i = int(round(v))
        out.add(str(i))
    else:
        out.add(f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ","))
        out.add(f"{v:.1f}".replace(".", ","))
    return {_num_key(x) for x in out}


def _chart_rows(osl: OutlineSlide, ctx: AuditContext) -> list[list[tuple[str, float]]]:
    """(category, value) rows of each series the slide's chart shows."""
    out: list[list[tuple[str, float]]] = []
    for spec in (osl.content.chart, osl.content.chart2):
        if spec is None:
            continue
        cats = list(spec.categories or [])
        for ser in spec.series or []:
            if cats and ser.values:
                out.append(list(zip(cats, ser.values)))
        if ctx.outline is not None:
            for sid in spec.series_ids or []:
                ser = ctx.outline.series_by_id(sid)
                if ser is not None and ser.categories and ser.values:
                    out.append(list(zip(ser.categories, ser.values)))
    return out


def _content_stems(text: str) -> set[str]:
    return {w[:5] for w, _, _ in tokens(text) if len(w) >= 4 and not w.isdigit()}


def value_unit(category: str, value: float, sents: list[str]) -> Optional[tuple[str, str]]:
    """(unit, phrase) of the value as the source writes it, in the sentence that shares most words with its category."""
    forms = _num_forms(value)
    cat = _content_stems(category)
    best: Optional[tuple[int, str, str]] = None
    for s in sents:
        for n in _NUM_RE.finditer(s):
            if _num_key(n.group(0)) not in forms:
                continue
            score = len(cat & _content_stems(s))
            u = unit_after(s[n.end() :])
            phrase = _clean(s[n.start() : n.end() + 30])
            if best is None or score > best[0]:
                best = (score, u or "", phrase)
    if best is None or not best[1]:
        return None
    return best[1], best[2]


@check(CHART_MIXED_UNITS)
def chart_mixed_units(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        osl = _outline_slide(ctx, s)
        if osl is None:
            continue
        sents = sentences(osl.notes or "") + (sentences(ctx.brief_text) if ctx.brief_text else [])
        if not sents:
            continue
        for rows in _chart_rows(osl, ctx):
            if len(rows) < 2:
                continue
            got = [(c, value_unit(c, v, sents)) for c, v in rows]
            units = [(c, u) for c, u in got if u is not None]
            kinds = {u[0] for _, u in units}
            if len(units) < 2 or len(kinds) < 2:
                continue
            chart = next((e for e in s.elements if e.type == "chart"), None)
            shown = _quoted([u[1] for _, u in units], n=4, width=40)
            out.append(ctx.new_issue(CHART_MIXED_UNITS, s.index, f"на одной диаграмме значения разных величин: {shown}", bboxes=[chart.bbox_frac] if chart is not None else [], element_ids=[chart.id] if chart is not None else [], details={"units": {c: u[0] for c, u in units}}))
            break
    return out


# ------------------------------------------------------------------ writer_failed

_WHY_RU = {
    "failed": "модель недоступна — текст не написан",
    "refused": "модель отказалась писать текст по этой теме",
    "refuse": "модель отказалась писать текст по этой теме",
    "private": "тема похожа на частное лицо — текст не написан",
    "skipped": "не хватило времени написать текст",
}


@check(WRITER_FAILED)
def writer_failed(ctx: AuditContext) -> list[Issue]:
    status = writer_status(getattr(ctx, "writer", None))
    if status is None or status == "written" or ctx.outline is None:
        return []
    kinds = [_kind(o) for o in ctx.outline.slides]
    content = [k for k in kinds if k not in ("title", "agenda", "thanks")]
    if any(k != "section" for k in content):
        return []
    why = _WHY_RU.get(status, "текст не написан")
    return [ctx.new_issue(WRITER_FAILED, 0, f"{why}: на {len(content)} содержательных слайдах только разделители разделов", details={"status": status, "dividers": len(content)})]


__all__ = [
    "LINE_FRAGMENT", "FIGURE_IS_TIME", "ORPHAN_OPENER", "DUPLICATE_HEADING", "CHART_MIXED_UNITS", "WRITER_FAILED",
    "written_deck", "has_predicate", "strict_verb", "loose_verb", "ends_on_governing_word", "fragment_reason",
    "figure_source_kind", "orphan_reason", "unit_after", "value_unit", "slide_lines", "sentences", "Line",
]
