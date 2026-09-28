"""Writer mode: a sentence of the writer's text shown on a slide says what the sentence says (gate 4 G4-1, G4-3, G4-6).

- `safe_cut` shortens a sentence only where a clause ends: the head keeps its own finite verb (a relative clause's verb
  is not the head's), never ends on a governing or particle word («только», «такими», «как», a preposition), never
  drops a contrasting clause («…, но отключилась на секунду раньше» — dropping it inverts the meaning), never leaves a
  «такой / так» without the «как» it announces. None when no cut is safe; `fit` then keeps the whole sentence (the
  composer sets it smaller) — never a fragment («6 июня 1944 года союзные силы США», «Выключение двигателя произошло
  только»).
- `standalone` makes a sentence readable on its own card, line or label: a leading connector goes («Также компания
  приобрела…» → «Компания приобрела…»), a leading «он / она» and a possessive «его / её» take the name the text gives
  before it («Он стал первым…» → «Гагарин стал первым…», «её доход» → «доход VK») when exactly one name of that
  gender stands before it; None when the sentence still leans on another one.
- `figure_ok` tells a key figure from a clock time («в 10 часов 53 минуты»), a project or model number («проекта
  22220», «№ 22-10»), a bound of a requirement («не более 170 см», «до 68—70 кг») and a figure of a requirements list;
  `hedged_value` keeps the sentence's «около / более / до» in the value («около 3800 т»).

No model call; nothing here adds a word the text does not have (a name comes from the text itself)."""

from __future__ import annotations

import re
from typing import Optional

from verstka.planning import heuristics as H

# ------------------------------------------------------------------ words

_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]*")

# nouns and adverbs that end like a verb (past «-ал/-ела/-ило/-ули», present «-ет/-ит/-ут/-ат/-ёт»)
_NOT_VERBS = frozenset(
    """около мало немало сначала начало правило правила число дело дела тело тела село села зеркало крыло мыло сало жало
    одеяло покрывало стол пол зал бал вал канал капитал сигнал материал персонал потенциал интервал финал идеал журнал
    арсенал генерал адмирал маршал штурвал вокзал скандал ритуал терминал подвал перевал шквал минерал кардинал оригинал
    пьедестал отдел раздел предел пробел ангел пепел посол угол престол символ протокол футбол глагол стул аул гул караул
    тыл пыл канала капитала сигнала материала персонала журнала генерала адмирала маршала финала зала отдела раздела
    предела ангела символа протокола футбола стула тыла урала земли цели роли модели соли боли воли доли недели детали
    медали эмали печали спирали магистрали стили автомобили модули пули мили пыли панели отели дуэли метели постели сили
    могилы стрелы пчелы скалы силы дали цели
    бюджет совет предмет ответ кабинет пакет билет интернет маркет привет запрет портрет секрет скелет паритет приоритет
    авторитет факультет университет комитет менталитет суверенитет нейтралитет иммунитет атлет балет буфет букет жилет
    минарет планет ракет монет примет газет лет свет цвет расцвет рассвет завет обет клиент процент момент документ
    элемент сегмент компонент инструмент аргумент эксперимент президент студент пациент континент парламент
    кредит лимит визит аудит депозит гранит магнит бандит транзит реквизит алфавит аппетит динамит орбит спутник
    ребят котят салют уют парашют абсолют валют приют минут маршрут институт атрибут статут лоскут редут батут мазут
    формат аппарат автомат кандидат депутат штат солдат климат дипломат результат комбинат препарат агрегат мандат
    сенат брат квадрат плакат адресат концентрат халат салат карат эмират пират магнат примат шпагат дат зарплат
    самолёт самолет полёт полет отчёт отчет расчёт расчет счёт счет учёт учет взлёт взлет налёт налет перелёт перелет
    звездолёт звездолет вертолёт вертолет пулемёт пулемет миномёт миномет переплёт переплет огнемёт огнемет гранатомёт
    гранатомет пролёт пролет помёт помет омлет берет пистолет арбалет силуэт дуэт квартет трафарет амулет сюжет метеорит
    гепатит бронхит колит кнут прут жгут атомат триумвират суррогат пролетариат секретариат консулат орбит быт кит щит
    бюджет коттедж функционал терминал мемориал сериал вокал бокал интеграл портал квартал трибунал криминал маргинал
    вандал феодал нахал театрал континентал крокодил отдел раздел удел придел котёл котел дятел орёл орел волейбол
    баскетбол гандбол""".split()
)
_PAST_RE = re.compile(r"(?:[аеёиоуыюя]л|[аеёиоуыюя]л[аои]|ш[её]л|шл[аои])(?:сь|ся)?$")
_PRES_RE = re.compile(r"(?:ет|ёт|ит|ут|ют|ат|ят|[еёиуюая]тся)$")
# past forms without «-л» and short common verbs
_IRREGULAR = frozenset(
    """мог смог помог могла смогла помогла могли смогли помогли могло смогло вторгся вторглась вторглись вторглось возник
    возникла возникли возникло достиг достигла достигли достигло погиб погибла погибли погибло исчез исчезла исчезли
    проник проникла проникли привёз привез привезла привезли принёс принес принесла принесли вырос выросла выросли рос
    росла росли умер умерла умерли шёл шел шла шли пошёл пошел пошла пошли пришёл пришел пришла пришли ушёл ушел ушла ушли
    вошёл вошел вошла вошли нашёл нашел нашла нашли прошёл прошел прошла прошли перешёл перешел перешла перешли произошёл
    произошел произошла произошли подошёл подошел подошла подошли вышел вышла вышли зашёл зашел зашла зашли сжёг сжег
    лёг лег легла легли привлёк привлек привлекла привлекли отвлёк увлёк увлек стёр стер запер есть нет""".split()
)
_AUX = frozenset("был была было были будет будут является являются являлся являлась являлось являлись стал стала стало стали".split())
_PREDICATIVE = frozenset("можно нужно необходимо нельзя известно возможно надо следует удалось пришлось".split())
_SHORT_PART_RE = re.compile(r"^[а-яё]{3,}(?:[аяе]н|[её]н|[иы]т|ят|ыт|ут|от)[аоы]?$")  # «основана», «создан», «принято», «убит», «взяты»


def _low(w: str) -> str:
    return (w or "").lower().replace("ё", "е")


def is_verb(word: str, first: bool = False) -> bool:
    """A finite verb form (past, present or future, reflexive too) — not a noun or an adverb that ends like one. A
    capitalised word counts only as the sentence's first (`first`)."""
    w = (word or "").strip("«»\"'()[],.;:!?")
    if not w or (w[:1].isupper() and not first):
        return False
    lw = w.lower()
    if lw in _NOT_VERBS or _low(lw) in _NOT_VERBS:
        return False
    if lw in _IRREGULAR or lw in _AUX or lw in _PREDICATIVE:
        return True
    if len(lw) < 4:
        return False
    if _PAST_RE.search(lw):
        return True
    return bool(_PRES_RE.search(lw)) and (len(lw) >= 5 or lw.endswith("ёт"))


# ------------------------------------------------------------------ the main clause and its predicate

# a subordinate clause with its own verb: from its word to the next comma (or the end)
_SUBORD_RE = re.compile(
    r"(?:^|,\s+|\s[—–]\s)(?:(?:в|на|с|к|по|о|от|до|из|у|за|для|при|через|над|под|про|между|среди)\s+)?"
    r"(?:котор\w+|что(?!\s+(?:и|же))|чтобы|где|куда|откуда|когда|если|хотя|пока|поскольку|так\s+как|потому\s+что|будто|словно|ибо)(?![\wё])[^,;]*",
    re.I,
)
_DASH_COPULA_RE = re.compile(r"[^\s—–-]\s+[—–]\s+(?:это\s+)?\S")


def main_clause(text: str) -> str:
    """The text without its subordinate clauses («Первыми людьми, которые встретили космонавта» → «Первыми людьми»)."""
    return _SUBORD_RE.sub(" ", text or "")


def has_predicate(text: str) -> bool:
    """The text's own main clause has a predicate: a finite verb, an auxiliary with a short participle («было
    принято», «была основана»), a predicative («можно») or a dash for the verb («Электромобиль — это автомобиль»)."""
    t = main_clause(text)
    t = re.sub(r"«[^«»]*»", " ", t)
    if _DASH_COPULA_RE.search(t):
        return True
    toks = _TOKEN_RE.findall(t)
    for i, w in enumerate(toks):
        if is_verb(w, first=(i == 0)):
            return True
        lw = w.lower()
        if _SHORT_PART_RE.match(lw) and lw not in _NOT_VERBS and i > 0 and toks[i - 1].lower() in ("был", "была", "было", "были", "будет", "будут"):
            return True
    # «введены требования», «созданы две бизнес-группы»: a short participle as the verb at the start
    return bool(toks) and bool(re.match(r"^(?:[а-яё]+(?:ан|ян|ен|ён)[аоы]|[а-яё]+[иы]т[аоы])$", toks[0].lower())) and toks[0].lower() not in _NOT_VERBS


# ------------------------------------------------------------------ where a clause ends

# words a head never ends on: a particle, a governing word, a hedge, a preposition, a conjunction
_BAD_END = frozenset(
    """только лишь уже ещё еще также тоже даже именно так такой такая такое такие таких такими таким такого такую столь
    настолько как чем тот та то те тех тем того той ту этот эта это эти этих этим этого этой эту все всех всем более менее
    около почти примерно свыше порядка не ни и а но или либо что чтобы если когда где который которая которое которые
    в во на с со к ко по о об обо от до из у за для при без через над под про между перед после против среди вокруг
    вместо кроме ради сквозь согласно благодаря вследствие из-за один одна одно одни одного одной ряд ряда числе
    стал стала стало стали является являются был была было были будет будут""".split()
)
# the clause after the cut contrasts the head: dropping it changes the meaning
_CONTRAST_RE = re.compile(
    r"^[,;]?\s*(?:но|а(?!\s+также)|однако|хотя|зато|тогда\s+как|в\s+то\s+время\s+как|несмотря|впрочем|при\s+этом\s+не|но\s+и)(?![\wё])",
    re.I,
)
# a correlative that announces its clause («с такими событиями, …, как…», «так…, что…»)
_CORRELATIVE_RE = re.compile(r"(?<![\wё])(?:так(?:ой|ая|ое|ие|их|ими|им|ого|ую)?|столь|настолько|тот\s+же|та\s+же|те\s+же|то\s+же)(?![\wё])", re.I)
_ANNOUNCED_RE = re.compile(r"(?<![\wё])(?:как|что|чтобы|будто)(?![\wё])", re.I)
# a verb that takes the clause after it («сообщил, что…», «считается, что…»)
_SAY_RE = re.compile(
    r"(?:сообщ|заяв|отмет|подчеркн|объяв|указ|призна|счита|полага|утвержда|говор|писа|реш|известн|предполага|ожида|оказал|выясн|"
    r"доказ|показ|увер|напомн|пояснил|уточнил|добавил|рассказ|опасал|надеял)\w*$",
    re.I,
)
# where a clause may end (the cut is made before it): a relative clause, «, что …» after a noun, a participle or a
# gerund phrase, an additive clause, an enumeration of examples, a semicolon, a dash, a prepositional adjunct
_CUT_RE = re.compile(
    r",\s+(?=(?:котор\w+|что|где|куда|откуда|когда|включая|в\s+том\s+числе|из\s+них|среди\s+которых|а\s+также|и\s+|"
    r"таки[ех]\s+как|например|в\s+частности|особенно|причём|причем|в\s+результате|после\s+чего|что\s+привело|став|начав|начиная|"
    r"завершив|сделав|окружив|использ\w+|большинство)(?![\wё]))"
    r"|,\s+(?=[а-яё]{3,}(?:вш|ющ|ящ|ащ|ущ|енн|ённ|анн|янн|ем|им)[а-яё]*(?![\wё]))"
    r"|,\s+(?=[а-яё]{3,}(?:ав|ив|ыв|ев|ув|яв|авшись|ившись|явшись)(?![\wё]))"
    r"|;\s+|\s[—–]\s"
    r"|\s(?=(?:после|из-за|благодаря|несмотря\s+на|в\s+результате|с\s+целью|для\s+того)\s)",
    re.I,
)


def _words(t: str) -> list[str]:
    return (t or "").split()


def head_ok(head: str, rest: str, min_words: int = 4) -> bool:
    """A head cut off a sentence (`rest` is what follows it) says a whole thing: its own predicate, its quotes and
    parentheses closed, not ending on a governing / particle word, not before a contrast, no correlative left
    without its clause, no «сообщил» without what was said."""
    h = H.strip_end(head).rstrip(",;:—– ")
    ws = _words(h)
    if len(ws) < min_words or h.count("«") != h.count("»") or h.count("(") != h.count(")"):
        return False
    last = ws[-1].strip("«»\"'()").lower()
    if last in _BAD_END or re.fullmatch(r"[—–-]", last):
        return False
    r = (rest or "").lstrip()
    if _CONTRAST_RE.match(r):
        return False
    if _CORRELATIVE_RE.search(h) and _ANNOUNCED_RE.search(re.split(r"[.!?]", r)[0]):
        return False
    if re.match(r"^[,:]?\s*(?:что|как|чтобы|будто)(?![\wё])", r, re.I) and (_SAY_RE.search(last) or is_verb(last)):
        return False  # «…сообщил, что Россия строит…»: what was said is the sentence
    if re.search(r"(?<![\wё])(?:только|лишь)$", h, re.I):
        return False
    if re.search(r"(?<![\wё])не$", h, re.I):
        return False
    return has_predicate(h)


MIN_SHARE = 0.45  # a head keeps at least this share of its sentence's words: a shortening, not another statement


def safe_cut(sentence: str, max_words: int, min_words: int = 4, min_share: float = MIN_SHARE) -> Optional[str]:
    """The sentence at most `max_words` long: as it is, or its longest head that ends where a clause ends and says a
    whole thing (head_ok), keeps at least `min_share` of the sentence and does not drop the list the sentence
    announces with a colon right after the cut («…кандидаты, соответствующие требованиям: возраст…»); None when no
    cut is safe."""
    s = H.strip_end(sentence or "")
    n = len(_words(s))
    if n <= max_words:
        return s
    best: Optional[str] = None
    for m in _CUT_RE.finditer(s):
        head = s[: m.start()].rstrip(" ,;:—–")
        k = len(_words(head))
        if k > max_words:
            break
        rest = s[m.start():]
        first_clause = re.split(r"[,;]\s", rest.lstrip(" ,;—–"), maxsplit=1)[0]
        if ":" in first_clause:
            continue
        if k < min_share * n:
            continue
        if head_ok(head, rest, min_words):
            best = H.strip_end(head)
    return best


def fit(sentence: str, max_words: int) -> str:
    """The sentence shortened safely (safe_cut), else whole: never a fragment."""
    s = H.strip_end(sentence or "")
    return safe_cut(s, max_words) or s


def cut_is_safe(line: str, sentence: str) -> Optional[bool]:
    """A line that is the start of the sentence: whether it was cut where a clause ends (head_ok). None when the line
    is not a strict start of the sentence."""
    a, b = _norm_line(line), _norm_line(sentence)
    if not a or not b.startswith(a) or len(a) >= len(b) or len(_words(a)) < 2:
        return None
    nxt = b[len(a):]
    if nxt[:1].isalnum():
        return False  # cut inside a word
    rest = H.strip_end(sentence)
    # the same place in the original sentence: the number of words the line has
    k = len(_words(H.strip_end(line)))
    orig_words = _words(rest)
    tail = " ".join(orig_words[k:])
    head = " ".join(orig_words[:k])
    boundary = re.match(r"^\s*(?:[,;]|[—–])", nxt) is not None or bool(re.match(r"^\s*(?:после|из-за|благодаря|несмотря|в\s+результате|с\s+целью|для\s+того)\s", nxt, re.I))
    if not boundary:
        return False
    sep = "" if head.endswith((",", ";")) else " "
    return head_ok(head, (sep + tail) if not head.endswith((",", ";")) else ", " + tail)


def _norm_line(t: str) -> str:
    t = re.sub(r"\s+", " ", (t or "").replace(" ", " ")).strip()
    t = H.strip_end(t)
    return t[:1].lower() + t[1:]


# ------------------------------------------------------------------ a sentence on its own

_CONNECTOR_RE = re.compile(
    r"^(?:Также|Кроме\s+того|Помимо\s+этого|Помимо\s+того|При\s+этом|Более\s+того|К\s+тому\s+же|Вместе\s+с\s+тем|Кроме\s+этого|"
    r"Тем\s+не\s+менее|Между\s+тем|В\s+свою\s+очередь|Также\s+и)(?![\wё])[,]?\s+",
)


def strip_connector(text: str) -> str:
    """«Также компания приобрела…» → «Компания приобрела…»; «Кроме того, …» → «…»."""
    t = (text or "").strip()
    m = _CONNECTOR_RE.match(t)
    if not m or len(_words(t[m.end():])) < 3:
        return t
    return H.cap_first(t[m.end():])


_SUBJ_PRON_RE = re.compile(r"^(Он|Она|Оно)\s+(?=[а-яё])")
# «14 апреля 1961 года он получил…», «В 1527 году она привезла…»: the subject after a leading time
_MID_PRON_RE = re.compile(r"^(?:(?:[ВвСсКк]|[Пп]осле|[Дд]о)\s+)?(?:\d{1,2}\s+[а-яё]+\s+)?(?:\d{4}\s+(?:года|году|г\.)\s+)?(?:[а-яё]+\s+){0,1}?(он|она|оно)\s+(?=[а-яё]+(?:л|ла|ло|ет|ит|ся|сь)(?![\wё]))")
_POSS_RE = re.compile(r"(?<![\wё])([Ее]го|[Ее]ё|[Ее]е)\s+((?:[а-яё]+(?:ый|ий|ой|ая|яя|ое|ее|ые|ие|ого|его|ому|ему|ым|им|ую|юю|ых|их|ыми|ими)\s+){0,2}[а-яё]{3,})(?![\wё])")
_PREP_PRON_RE = re.compile(r"(?<![\wё])([Вв]|[Оо])\s+(ней|нём|нем)(?![\wё])")
# a pronoun or a demonstrative that leans on the sentence before
_PERS_RE = re.compile(r"(?<![\wё])(?:он|она|оно|они|его|её|ее|их|ему|ей|им|ним|ней|нём|нем|них|ними|нею)(?![\wё])", re.I)
_DEM_RE = re.compile(r"(?<![\wё])(?:этот|эта|это|эти|этого|этой|этих|этому|этим|этом|эту|тот|та|те|такой|такая|такое|такие|таких|таким|там|тогда|тот\s+же)(?![\wё])", re.I)
_LEAN_OK_RE = re.compile(r"(?:[—–]\s+это|при\s+этом|кроме\s+того|тем\s+не\s+менее|в\s+том\s+числе|тем\s+самым|к\s+тому\s+же|то\s+есть|что\s+это|таки[ехм]\s+как|так\s+как|до\s+того|после\s+того|с\s+тех\s+пор|в\s+то\s+время|в\s+этом\s+году|в\s+том\s+же)(?![\wё])", re.I)
_FUNCTION_CAPS = frozenset("В Во На С Со По К Ко До Из У За Для При После Перед Через Также Однако Кроме Затем Тогда Там Здесь Впервые Это Этот Эта Эти Он Она Оно Они Его Её Ее Их И А Но".split())


def leans(text: str, names: Optional[set] = None) -> bool:
    """The sentence leans on the one before it: a demonstrative among its first six words («Такой тип транспорта…»,
    «Этот полёт…»), or a personal or possessive pronoun among its first ten words with no name before it in the
    sentence («Он стал…», «…был и её первый министр…», «В ней участвовали…»; not «Гагарин их успокоил»). `names`: the
    text's names (lowercase), a capitalised first word counts as one only when it is among them."""
    ws = _words(_LEAN_OK_RE.sub(" ", text or ""))
    if _DEM_RE.search(" ".join(ws[:6])):
        return True
    head = ws[:10]
    for i, w in enumerate(head):
        pw = w.strip("«»\"'(),.;:").lower()
        if not _PERS_RE.fullmatch(pw):
            continue
        if pw in ("они", "их", "им", "ими", "них", "ними"):
            # a plural: two names joined before it («Кривенков и Андрианов … их»), else it leans
            return not re.search(r"[А-ЯЁA-Z][\wё-]+\s+и\s+[А-ЯЁA-Z]", " ".join(head[:i]))
        for j, x in enumerate(head[:i]):
            core = x.strip("«»\"'(),.;:")
            if not core[:1].isupper() or core in _FUNCTION_CAPS:
                continue
            if j > 0 or (names and _low(core) in names) or re.match(r"[A-Z]", core) or (len(core) >= 2 and core.isupper()):
                return False
        return True
    return False


def _nominative_forms(deck: str) -> dict[str, str]:
    """Capitalised names the deck writes as a subject (before a verb): {name: gender by its verb}. «Гагарин был
    торжественно встречен» → {"Гагарин": "m"}, «VK была основана» → {"VK": "f"}, «Екатерина II ввела» (after it) → f."""
    out: dict[str, dict[str, int]] = {}
    name_re = r"((?:[A-Z][\w+\-]*(?:\.[a-z]{2,4})?|[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?|[А-ЯЁ]{2,})(?:[ \t]+(?:[IVX]{1,4}|[А-ЯЁ][а-яё]+|[A-Z][\w+\-]*)){0,2})"
    for m in re.finditer(rf"(?<![\wё«-]){name_re}\s+(?:[а-яё]+о\s+)?([а-яё]{{2,}}?(?:л|ла|ло|ли)(?:сь|ся)?)(?![\wё])", deck or "", re.M):
        _count(out, m.group(1), m.group(2))
    # «…, ввела, по-видимому, Екатерина II.»: a name after its verb at the end of a sentence
    for m in re.finditer(rf"(?<![\wё])([а-яё]{{2,}}?(?:л|ла|ло|ли)(?:сь|ся)?)(?:,\s+[^,.]{{1,30}},)?\s+{name_re}(?=[.!?]|$)", deck or "", re.M):
        _count(out, m.group(2), m.group(1))
    inside = {_low(m.group(1)) for m in re.finditer(r"(?<=[\wё,;:»)][ \t])([А-ЯЁ][а-яё]+)", deck or "")}
    res = {}
    for name, v in out.items():
        parts = name.split()
        while len(parts) >= 2 and re.search(r"(?:и|е|у|ой|ом|ам|ах|ей|ы)$", parts[0]) and not re.fullmatch(r"[IVX]{1,4}", parts[1]):
            parts = parts[1:]  # «В Азии Япония стремилась»: «Азии» is where, «Япония» who
        name = " ".join(parts)
        first = parts[0]
        if re.match(r"[А-ЯЁ][а-яё]+$", first) and len(parts) == 1 and re.search(r"(?:и|е|у|ой|ом|ам|ах|ей|ых|ым)$", first):
            continue  # «Мексики высадился», «в Париже насчитывалось»: a name in another case, not the subject
        if not (re.match(r"[A-Z]", first) or first.isupper() or any(_low(x)[: max(4, len(first) - 2)] == _low(first)[: max(4, len(first) - 2)] for x in inside)):
            continue  # a sentence's first word («Полёт», «Война»), not a name
        if name in res:
            continue
        ranked = sorted(v.items(), key=lambda kv: -kv[1])
        if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
            res[name] = ranked[0][0]
    return res


def _count(out: dict, name: str, verb: str) -> None:
    lw = verb.lower()
    if lw in _NOT_VERBS or not is_verb(lw):
        return
    base = re.sub(r"(?:сь|ся)$", "", lw)
    g = "f" if base.endswith("ла") else "n" if base.endswith("ло") else "p" if base.endswith("ли") else "m" if base.endswith("л") else ""
    first = name.split()[0]
    if not g or first in ("В", "На", "С", "По", "К", "До", "После", "При", "Для", "Это", "Этот", "Эта", "Он", "Она", "Оно", "Они", "Также", "Однако", "Кроме", "Затем", "Тогда", "Там", "Здесь", "Впервые", "Первым", "Первой"):
        return
    if re.match(r"^(?:Январ|Феврал|Март|Апрел|Ма[йя]|Июн|Июл|Август|Сентябр|Октябр|Ноябр|Декабр)", first):
        return
    out.setdefault(name, {}).setdefault(g, 0)
    out[name][g] += 1


_INSTR_PERSON = r"([А-ЯЁ][а-яё]+(?:ем|ом|ым|им))\s+([А-ЯЁ][а-яё]+(?:ым|ом|ем|иным|ыным))"


def _person_pair(sentence: str) -> Optional[str]:
    """«…разработанный Алексеем Кривенковым и Дмитрием Андриановым» → «Алексей Кривенков и Дмитрий Андрианов»: two people
    the sentence names in the instrumental, in the nominative (for a following «они»); None otherwise."""
    m = re.search(rf"{_INSTR_PERSON}\s+и\s+{_INSTR_PERSON}", sentence or "")
    if not m:
        return None

    def first(w: str) -> str:
        return w[:-2] + "й" if w.endswith("ем") else w[:-2] if w.endswith(("ом", "ым", "им")) else w

    def last(w: str) -> str:
        return w[:-2] if w.endswith(("ым", "ом", "им")) else w[:-2] + "й" if w.endswith("ем") else w

    return f"{first(m.group(1))} {last(m.group(2))} и {first(m.group(3))} {last(m.group(4))}"


def _genitive(name: str) -> Optional[str]:
    """«Гагарин» → «Гагарина», «Екатерина II» → «Екатерины II», «Россия» → «России»; a Latin or upper-case name as it is."""
    parts = name.split()
    w = parts[0]
    if re.match(r"[A-Z]", w) or w.isupper():
        return name
    lw = w.lower()
    if lw.endswith("ия"):
        g = w[:-1] + "и"
    elif lw.endswith("я"):
        g = w[:-1] + "и"
    elif lw.endswith("а"):
        g = w[:-1] + ("и" if lw[-2:-1] in "гкхжшчщ" else "ы")
    elif re.search(r"[бвгджзклмнпрстфхцчшщ]$", lw):
        g = w + "а"
    elif lw.endswith("й"):
        g = w[:-1] + "я"
    else:
        return None
    return " ".join([g, *parts[1:]])


def _prepositional(noun: str) -> Optional[str]:
    """«Война» → «войне», «Германия» → «Германии», «полёт» → «полёте» (a common noun lowercased)."""
    w = noun
    lw = w.lower()
    if lw.endswith("ия"):
        out = w[:-1] + "и"
    elif lw.endswith(("а", "я")):
        out = w[:-1] + "е"
    elif re.search(r"[бвгджзклмнпрстфхцчшщ]$", lw):
        out = w + "е"
    elif lw.endswith("й"):
        out = w[:-1] + "е"
    else:
        return None
    return out


def _antecedents(before: list[str], names: dict[str, str]) -> list[tuple[str, str]]:
    """The names of `names` (nominative → gender) the sentences before mention, the nearest first."""
    out: list[tuple[str, str]] = []
    for sn in reversed(before):
        low = sn
        for name, g in names.items():
            stem = name.split()[0]
            stem = stem if (re.match(r"[A-Z]", stem) or stem.isupper()) else stem[: max(4, len(stem) - 2)]
            if re.search(rf"(?<![\wё]){re.escape(stem)}", low) and all(name != x for x, _ in out):
                out.append((name, g))
        if out:
            break
    return out


def standalone(text: str, before: list[str], deck: str = "", names: Optional[dict[str, str]] = None) -> Optional[str]:
    """The sentence readable on its own card, line or label: its leading connector dropped; a leading «Он / Она» and a
    possessive «его / её» replaced by the one name of that gender the sentences `before` mention (the text's own
    nominative form of it, `names` or read from `deck`); «в ней / в нём» by the noun the sentence before starts with.
    Unchanged when it leans on nothing; None when it still leans on another sentence."""
    t = strip_connector(text)
    names = names if names is not None else _nominative_forms(deck)
    low_names = {_low(n.split()[0]) for n in names}
    if not leans(t, low_names):
        return t
    cands = _antecedents(before, names)
    m = re.search(r"(?:^|,\s+)(Они)\s+(?=[а-яё]+ли(?:сь)?(?![\wё]))", t, re.I) if before else None
    if m:
        pair = _person_pair(before[-1])
        if pair:
            head = t[: m.start(1)]
            t = head + (pair if head else pair) + t[m.end(1):]
    m = _SUBJ_PRON_RE.match(t) or _MID_PRON_RE.match(t)
    if m:
        want = {"он": "m", "она": "f", "оно": "n"}[m.group(1).lower()]
        hit = [n for n, g in cands if g == want]
        if len(hit) == 1:
            t = t[: m.start(1)] + hit[0] + t[m.end(1):]
    m = _POSS_RE.search(t)
    if m and is_verb(m.group(2).split()[-1]):
        m = None  # «Его пили только мужчины»: an object, not a possessive
    if m:
        want = "m" if m.group(1).lower() == "его" else "f"
        hit = [n for n, g in cands if g == want or (want == "m" and g == "n")]
        gen = _genitive(hit[0]) if len(hit) == 1 else None
        if gen:
            t = t[: m.start()] + m.group(2) + " " + gen + t[m.end():]
            if m.start() == 0:
                t = H.cap_first(t)
    m = _PREP_PRON_RE.search(t)
    if m and before:
        first = re.match(r"^([А-ЯЁ][а-яё]{3,})\s+([а-яё]+)", H.strip_end(before[-1]))
        if first and is_verb(first.group(2)):
            noun = first.group(1)
            fem = noun.lower().endswith(("а", "я"))
            if (m.group(2) == "ней") == fem:
                pp = _prepositional(noun if any(noun.lower() in _low(x) and noun in x[1:] for x in before) else noun.lower())
                if pp:
                    t = t[: m.start()] + m.group(1) + " " + pp + t[m.end():]
    return t if not leans(t, low_names) else None


# ------------------------------------------------------------------ key figures

# a time of day: «в 10 часов 53 минуты», «в 9:07», «к 18 часам»
_CLOCK_RE = re.compile(
    r"(?<![\wё])(?:в|к|около|до|после|с|по)\s+(\d{1,2})\s+час\w*(?:\s+(\d{1,2})\s+минут\w*)?|(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])",
    re.I,
)
# a number that names something: a project, a model, a series, a document («ледоколы проекта 22220», «№ 22-10»)
_CODE_BEFORE_RE = re.compile(r"(?:проект\w*|№|номер\w*|модел\w*|сери[июя]|тип[аеу]?|марк[иа]|индекс\w*|код\w*|постановлени\w*|указ\w*|приказ\w*|стандарт\w*|ГОСТ)\s*$", re.I)
# a bound of a requirement or a limit: «не более 170 см», «до 68—70 кг», «не старше 30 лет»
_BOUND_BEFORE_RE = re.compile(r"(?:не\s+(?:более|менее|свыше|больше|меньше|старше|моложе|выше|ниже|дольше)|максимум|минимум|от|до)\s*$", re.I)
# «выросла до 330»: «до» after a change is the level reached, not a bound
_CHANGE_BEFORE_RE = re.compile(r"(?:вырос|возрос|увелич|сниз|сократ|повыс|подня|упал|опуст|дорос|достиг|снизил|расшир|довел|довёл|дошл|сокращ|увеличен|рост)\w*(?:\s+\S+){0,3}\s+до\s*$", re.I)
_REQUIRE_RE = re.compile(r"требовани|должн[аоы]?(?![\wё])|услови[ея]|критери|ограничени|допуска|разрешал", re.I)
# a hedge the value keeps: «около 3800», «более 250», «почти 70»
_HEDGE_RE = re.compile(r"(?<![\wё])(около|более|свыше|почти|примерно|порядка|менее|не\s+менее|не\s+более|приблизительно|~)\s*$", re.I)


def figure_kind(sentence: str, start: int, end: int) -> Optional[str]:
    """Why the figure written at [start, end) of the sentence is not a key figure: «clock» (a time of day), «code» (a
    project or model number, a document's number), «bound» (a limit of a requirement), «requirement» (a figure of a
    requirements list); None for a figure."""
    s = sentence or ""
    for m in _CLOCK_RE.finditer(s):
        if m.start() <= start < m.end():
            return "clock"
    before = s[max(0, start - 40): start]
    if _CODE_BEFORE_RE.search(before) or re.match(r"^[-‑–]\d", s[end: end + 3]) or re.search(r"[-‑][A-Za-zА-Яа-яЁё]*$", before[-2:]):
        return "code"
    if _BOUND_BEFORE_RE.search(before) and not _CHANGE_BEFORE_RE.search(s[max(0, start - 80): start]):
        return "bound"
    colon = s.rfind(":", 0, start)
    if colon >= 0 and _REQUIRE_RE.search(s[:colon]):
        return "requirement"
    return None


def hedge_of(sentence: str, start: int) -> Optional[str]:
    """The hedge the sentence writes right before the figure starting at `start` («около», «более», «почти»)."""
    m = _HEDGE_RE.search((sentence or "")[max(0, start - 30): start])
    return re.sub(r"\s+", " ", m.group(1).lower()) if m else None


_SCALE_FORMS = (("тысяч", "тыс."), ("тыс", "тыс."), ("миллиард", "млрд"), ("млрд", "млрд"), ("миллион", "млн"), ("млн", "млн"), ("триллион", "трлн"), ("трлн", "трлн"))


def fix_scale(value: str) -> str:
    """«17,8 тыс» → «17,8 тыс.», «5 млн.» → «5 млн» (Russian style: «тыс.» with its period, «млн / млрд» without)."""
    v = re.sub(r"(?<![\wё])тыс(?![\wё.])", "тыс.", value or "")
    v = re.sub(r"(?<![\wё])(млн|млрд|трлн)\.", r"\1", v)
    return v
