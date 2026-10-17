// Плита 02 «Текст» (C-text, C-improve, C-errors): в заголовке — «Из файла» с подписью «.txt или .md» и меню выбора,
// справа подсказка о готовом тексте, на свёрнутом шаге — тема в кавычках и «Изменить»; тело `#p2-b2` — поле «О чём
// презентация» с печатающейся подсказкой, строкой под полем (подсказка агента, разбор текста, ошибка, чтение
// презентации) и счётчиком знаков, над полем в «Улучшить готовую» — заметка об исходной презентации. Разметка —
// boards/V2.dc.html, плита 02 и модуль tx. Строки под полем сменяются перекрёстным затуханием (p2-on / p2-off: уход
// 240 мс, вход 360 мс через 120 мс) и, пока гаснут, держат своё содержимое.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type MutableRefObject, type RefObject } from "react";
import { useApp } from "../../store";
import { SAMPLE_BRIEF } from "../../lib/createForm";
import { humanError } from "../../lib/errors";
import { templateStem } from "../../lib/templateFiles";
import type { ImproveSource } from "../../types";
import { cls } from "../kit/cls";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { Spinner } from "../kit/Spinner";
import { useSwap } from "../kit/useSwap";
import { useDeckWrap } from "../deck/useDeckFit";
import { hintTail, readyShort } from "./morph";
import { FileMenu, type FilePick } from "./FileMenu";
import { fileRefusal, TEMPLATE_BUSY } from "./ribbon";
import { ImproveNote, useHeld, useImproveOn, useModelOn, type NoteHeights } from "./ImproveNote";
import { useNarrow } from "./useNarrow";
import { DATA_ACCEPT, dataPanel, dropKind, hasTable } from "./dataRules";
import { DataPanel, DataZone, useFilesDrop, usePanelMotion } from "./DataPanel";
import { GoalsBox } from "./GoalsBox";
import {
  charsLabel, DECK_ACCEPT, deckError, fileKind, fileTextIssue, improveLive, improveShift, improveStep, MAX_TEXT_BYTES, sampleText, TEXT_ACCEPT, textError, writerOn,
  textLine, textPreview, TW, TW0, TW_FIRST_MS, TW_WAKE_MS, twBlink, twStep, hintText, type ImproveLive, type TextIssue, type TextLine, type Tw,
} from "./textRules";
import { usePhone } from "../shell/tier";

const show = (on: boolean) => (on ? "p2-on" : "p2-off");

const HINT_TOPIC = "Это тема — агент напишет полный текст";
const HINT_TOPIC_TAIL = ": ключевые факты, даты, формулы с пояснениями";
/** С файлами данных (V2 `txHintShort`, `txHintShortN`): текст — бриф, слайды — по данным. */
const HINT_BRIEF = "Это бриф — агент напишет текст по данным";
const HINT_BRIEF_N = "Бриф — текст по данным";
/** Пример «данные продаж» (GET /api/examples/data-sales-2026): бриф, 7 файлов и брендбук VK Cloud. */
export const DATA_EXAMPLE = "data-sales-2026";
/** Пустое поле, а текст агент не пишет (модель не подключена или не пишет тексты): нужен готовый текст. */
const HINT_READY = "Вставьте готовый текст — агент разложит его по слайдам";
const NO_FACTS = "Цифр и таблиц в тексте нет — слайды будут из формулировок";
const FIX = "Вставьте готовый текст или загрузите .txt и .md";

/** Кто пишет текст: `writer` — агент распишет тему (`writerOn`: сервер в режиме writer, модель подключена и пишет
 *  тексты — строка «Это тема — агент напишет…», «Взять пример» даёт тему, тема проходит проверку перед сборкой);
 *  `writes` — модель пишет тексты слайдов («…и допишет недостающее», иначе «…без переписывания»). Оба сужает
 *  переключатель «Модель пишет тексты» шага 03: без него сервер не пишет и тему. */
export function useWriting(): { writer: boolean; writes: boolean } {
  const { health, modelStatus, params } = useApp();
  const writes = useModelOn() && params.useModels;
  return { writer: writerOn({ health, status: modelStatus, useModels: params.useModels }), writes };
}

/** Состояние шага на обе части плиты (заголовок и тело): меню, выбор файла, чтение презентации, ошибка у поля,
 *  печатающаяся подсказка, разбор текста. Одно на приложение — его создаёт AppShell. */
export interface TextPlate {
  menu: boolean;
  setMenu(on: boolean): void;
  btnRef: RefObject<HTMLButtonElement>;
  inputRef: RefObject<HTMLInputElement>;
  taRef: RefObject<HTMLTextAreaElement>;
  /** Пункт меню: выбор файла (текст или презентация) или пример текста. */
  pick(k: FilePick): void;
  onFile(f: File): void;
  /** Имя презентации, которую сервер сейчас читает («Улучшить готовую»); null — не читает. */
  reading: string | null;
  /** Почему «Улучшить готовую» сейчас не выбирается (презентация уже читается, разбирается свой шаблон); null — выбирается. */
  deckOff: string | null;
  /** Что поле говорит о тексте (подсказка агента или разбор). Считается один раз на изменение текста и отдаётся
   *  заголовку, телу и полосе 02: разбор большого текста не повторяется на каждую часть плиты. */
  line: TextLine;
  /** Модель пишет тексты слайдов (подпись «Это готовый текст…» в заголовке). */
  writes: boolean;
  /** Тихая строка о ходе чтения («Модель не подключена — прочитаю презентацию по правилам») или о презентации, которую
   *  выбрали, пока разбирается свой шаблон («Сначала дождитесь разбора шаблона»); null — её нет. */
  info: string | null;
  /** Ошибка у поля: своя (`textIssue` — правила, файл) или неудача чтения презентации (строка области «Текст»). */
  issue: TextIssue | null;
  /** Номер ошибки: новая ошибка — новая строка (её `role=alert` читается заново). */
  issueSeq: number;
  /** Место печатающейся подсказки: «Взять пример» берёт её фразу, а очищенное поле продолжает с того же места. */
  tw: MutableRefObject<{ s: Tw; started: boolean }>;
  /** Ввод в поле. */
  type(v: string): void;
  /** «Взять пример»: тема из подсказки (V2 `txTake`); агент текст не пишет — готовый текст-пример. */
  take(): void;
  /** «Файлы с данными»: окно выбора нескольких файлов. */
  pickData(): void;
  dataRef: RefObject<HTMLInputElement>;
  /** Файлы, выбранные или отпущенные на плиту 02 («текст и данные вместе»): таблицы — в «Данные», текст — в поле,
   *  презентация — «Улучшить готовую». */
  onFiles(files: File[]): void;
  /** «Пример: данные продаж». */
  example(): void;
}

export function useTextPlate(): TextPlate {
  const {
    ui, dispatch, brief, setBrief, textIssue, setTextIssue, notices, clearNotice, uploadTemplate, templateId,
    composerText, takeComposerText, improveSource, takeImproveSource, analyzing,
  } = useApp();
  // разбирается свой шаблон (шаг 01): «Улучшить готовую» ждёт — обе выбирают свой шаблон
  const tplBusy = analyzing === "template";
  const tplBusyNow = useRef(tplBusy);
  tplBusyNow.current = tplBusy;
  const [menu, setMenu] = useState(false);
  const [reading, setReading] = useState<string | null>(null);
  const lastDeck = useRef("");
  // чтение презентации одно за раз: номер последнего чтения и занято ли (как `useTemplateUpload.start`)
  const readSeq = useRef(0);
  const readBusy = useRef(false);
  const { writer, writes } = useWriting();
  const { data } = useApp();
  const dataOn = data.cards.length > 0;
  // разбор текста — один раз на изменение текста, для заголовка, тела и полосы 02; с файлами данных хватает брифа
  // (слайды соберутся по данным) — короткий текст тогда «бриф», а не «нужен готовый текст»
  const line = useMemo(() => textLine(brief, writer || dataOn), [brief, writer, dataOn]);
  const btnRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dataRef = useRef<HTMLInputElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const tw = useRef({ s: TW0, started: false });
  const improveNow = useRef(ui.improve);
  improveNow.current = ui.improve;

  // текст пришёл не из поля (файл, пример, «Взять пример»): он уже не из презентации — «Улучшить готовую» кончается
  const replace = useCallback((t: string) => {
    setBrief(t);
    setMenu(false);
    if (improveNow.current) dispatch({ type: "set", patch: { improve: false } });
  }, [setBrief, dispatch]);

  // «Изменить текст» на результате: текст встаёт в поле (режим и параметры поставил editText)
  useEffect(() => {
    if (composerText === null) return;
    setBrief(composerText);
    takeComposerText();
  }, [composerText, setBrief, takeComposerText]);

  // «Улучшить готовую»: презентация прочитана — её текст встаёт в поле. Режим живёт, пока поле не очищено и выбран
  // шаблон этой презентации (V2 `txText`, `txImpOn`: `tpl === txTpl`); ввод в поле его не снимает. Режим кончился —
  // исходная презентация уходит из store: сборка её больше не отправляет.
  const applied = useRef<ImproveSource | null>(null);
  const live = useRef<ImproveLive | null>(null);
  useEffect(() => {
    if (improveSource && improveSource !== applied.current) {
      applied.current = improveSource;
      live.current = improveLive(improveSource.template_id ?? templateId, improveSource.brief);
      setBrief(improveSource.brief);
      return;
    }
    if (!ui.improve) {
      live.current = null;
      if (improveSource) takeImproveSource();
      return;
    }
    if (!live.current) return;
    const r = improveStep(live.current, brief, templateId);
    live.current = r.live;
    if (r.ends) dispatch({ type: "set", patch: { improve: false } });
  }, [improveSource, ui.improve, brief, templateId, setBrief, takeImproveSource, dispatch]);

  // шаг свернулся или ушёл с экрана — меню закрывается
  const txOpen = ui.screen === "create" && ui.open === "text" && !ui.more;
  useEffect(() => {
    if (!txOpen) setMenu(false);
  }, [txOpen]);

  // презентация выбрана, пока разбирается свой шаблон: она не принята — строка под полем говорит почему (уходит, когда
  // разбор кончился, или с новым текстом)
  const [refused, setRefused] = useState<string | null>(null);
  useEffect(() => {
    if (!tplBusy) setRefused(null);
  }, [tplBusy]);

  const readDeck = useCallback((f: File) => {
    // сервер разбирает свой шаблон: рядом не начинаем, и сказано почему (пункт меню тоже закрыт); уже читает
    // презентацию — её строка хода на виду
    if (tplBusyNow.current) return setRefused(fileRefusal("template", "deck"));
    if (readBusy.current) return;
    setRefused(null);
    const n = ++readSeq.current;
    readBusy.current = true;
    lastDeck.current = f.name;
    setReading(f.name);
    setTextIssue(null);
    clearNotice("text");
    void uploadTemplate(f, true, true).finally(() => {
      if (readSeq.current !== n) return; // строка принадлежит более новому чтению
      readBusy.current = false;
      setReading(null);
    });
  }, [uploadTemplate, setTextIssue, clearNotice]);

  const onFile = useCallback(async (f: File) => {
    setMenu(false);
    // у файла проверяется только тип: его текст ещё встанет в поле
    const bad = textError("", f, { writer });
    if (bad) return setTextIssue(bad);
    if (fileKind(f.name) === "deck") return readDeck(f);
    if (f.size > MAX_TEXT_BYTES) return setTextIssue({ kind: "file", text: `Файл «${f.name}» больше 2 МБ` });
    try {
      const raw = await f.text();
      // не UTF-8 (знак замены) и пустой файл — строкой у поля, в поле ничего не кладём
      const problem = fileTextIssue(raw, f.name);
      if (problem) return setTextIssue(problem);
      replace(raw.replace(/\r\n/g, "\n").trim());
    } catch (e) {
      setTextIssue({ kind: "file", text: humanError(e instanceof Error ? e.message : "", `Не удалось прочитать «${f.name}»`) });
    }
  }, [readDeck, replace, setTextIssue, writer]);

  const pick = useCallback((k: FilePick) => {
    setMenu(false);
    btnRef.current?.focus({ preventScroll: true });
    if (k === "sample") return replace(SAMPLE_BRIEF);
    const input = inputRef.current;
    if (!input) return;
    // выбор файла открывается в том же нажатии (иначе браузер его не откроет), поэтому accept ставится прямо в элемент
    input.accept = k === "text" ? TEXT_ACCEPT : DECK_ACCEPT;
    input.click();
  }, [replace]);

  const type = useCallback((v: string) => {
    setBrief(v);
    setMenu(false);
    setRefused(null);
  }, [setBrief]);

  const take = useCallback(() => {
    replace(sampleText(writer, TW[tw.current.s.i] ?? TW[0]));
    taRef.current?.focus({ preventScroll: true });
  }, [replace, writer]);

  // проверка перед сборкой (пусто, коротко) поднимает шаг «Текст» и ставит курсор в поле
  useEffect(() => {
    if (textIssue && (textIssue.kind === "empty" || textIssue.kind === "short")) taRef.current?.focus({ preventScroll: true });
  }, [textIssue]);

  const notice = notices.text?.kind === "error" ? notices.text.text : null;
  const info = refused ?? (notices.text?.kind === "info" ? notices.text.text : null);
  const issue: TextIssue | null = textIssue ?? (notice ? { kind: "file", text: deckError(notice, lastDeck.current) } : null);
  const seq = useRef({ key: null as string | null, n: 0 });
  const key = issue ? `${issue.kind}:${issue.text}` : null;
  if (key !== seq.current.key) seq.current = { key, n: key ? seq.current.n + 1 : seq.current.n };

  // файлы с данными: таблицы — в «Данные» (V2 `dtAttach`: «Улучшить готовую» кончается); .txt/.md с таблицей — тоже
  // данные, без таблицы — текст в поле; презентация — «Улучшить готовую» (если отпустили только её)
  const addData = data.addFiles;
  const onFiles = useCallback(async (list: File[]) => {
    setMenu(false);
    const tables: File[] = [];
    const texts: File[] = [];
    const decks: File[] = [];
    for (const f of list) {
      const k = dropKind(f.name);
      if (k === "deck") decks.push(f);
      else if (k === "text") {
        let raw = "";
        try {
          raw = f.size <= MAX_TEXT_BYTES ? await f.slice(0, 256 * 1024).text() : "";
        } catch {
          raw = "";
        }
        (raw && !hasTable(raw) ? texts : tables).push(f);
      } else tables.push(f);
    }
    if (tables.length) {
      if (improveNow.current) dispatch({ type: "set", patch: { improve: false } });
      addData(tables);
    }
    if (texts.length) void onFile(texts[0]);
    else if (decks.length && !tables.length) void onFile(decks[0]);
  }, [addData, onFile, dispatch]);
  const pickData = useCallback(() => {
    setMenu(false);
    dataRef.current?.click();
  }, []);
  const loadExample = data.loadExample;
  const example = useCallback(() => {
    setMenu(false);
    btnRef.current?.focus({ preventScroll: true });
    void loadExample(DATA_EXAMPLE);
  }, [loadExample]);

  const deckOff = reading ? "Презентация уже читается" : tplBusy ? TEMPLATE_BUSY : null;
  return {
    menu, setMenu, btnRef, inputRef, taRef, pick, onFile, reading, deckOff, line, writes, info, issue, issueSeq: seq.current.n, tw, type, take,
    pickData, dataRef, onFiles, example,
  };
}

const reducedMotion = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Печатающаяся подсказка поверх пустого поля (`p2-tph`) с курсором `p2-caret` — ритм V2 `twTick` (`twStep`). Идёт,
 *  пока поле пустое и открыт «Создать»; поле очистили — продолжает через 400 мс с того же места (V2 `twWake`). При
 *  «уменьшить движение» стоит первая фраза. Агент текст не пишет (`writer` — нет: строка под полем просит готовый
 *  текст) — тему подсказка не печатает: стоит начало готового текста-примера; смена — перекрёстным затуханием. */
function TypingHint({ live, tw, writer }: { live: boolean; tw: MutableRefObject<{ s: Tw; started: boolean }>; writer: boolean }) {
  const [s, setS] = useState(tw.current.s);
  const mode = useSwap(writer);
  useEffect(() => {
    if (!live || !writer || reducedMotion()) return;
    let t = 0;
    const tick = () => {
      const r = twStep(tw.current.s);
      tw.current.s = r.s;
      setS(r.s);
      t = window.setTimeout(tick, r.ms);
    };
    t = window.setTimeout(tick, tw.current.started ? TW_WAKE_MS : TW_FIRST_MS);
    tw.current.started = true;
    return () => window.clearTimeout(t);
  }, [live, writer, tw]);
  return (
    <span className={cls("p2-tph", mode.cls)} aria-hidden="true">
      {hintText(s, mode.shown)}
      <span className={cls("p2-caret", (!mode.shown || twBlink(s)) && "p2-caret-blink")} />
    </span>
  );
}

/** Заголовок плиты 02 справа (слот `h2`). */
export function TextHead({ tp }: { tp: TextPlate }) {
  const { ui, dispatch, brief, data } = useApp();
  const writes = tp.writes;
  const impOn = useImproveOn();
  const create = ui.screen === "create";
  const txOpen = create && ui.open === "text" && !ui.more;
  const closed = create && ui.open === "tpl";
  // готовый текст: агент разложит его по слайдам (V2 `txHintTop`) — не в «Улучшить готовую», не при ошибке
  const top = txOpen && tp.line.kind === "facts" && !impOn && !tp.issue && !tp.reading;
  const topText = writes ? "Это готовый текст — агент разложит его по слайдам и допишет недостающее" : "Это готовый текст — агент разложит его по слайдам без переписывания";
  const pv = textPreview(brief);
  const wrap = useDeckWrap();
  const phone = usePhone();
  return (
    <>
      {tp.menu && (
        <button type="button" className="tx-scrim" tabIndex={-1} aria-label="Закрыть выбор файла"
          onClick={() => {
            tp.setMenu(false);
            tp.btnRef.current?.focus({ preventScroll: true });
          }} />
      )}
      <div className={cls("p2-in tx-fg", show(txOpen))} style={{ display: "flex", alignItems: "center", gap: 12, animationDelay: "40ms" }}>
        {phone ? (
          // телефон (доска M-create): круглая кнопка со скрепкой справа от «Текст»
          <button ref={tp.btnRef} type="button" className="mp-rw" onClick={() => tp.setMenu(!tp.menu)} title="Текст .txt или .md, данные"
            aria-label="Из файла: текст .txt или .md, данные" aria-haspopup="menu" aria-expanded={tp.menu} aria-controls="tx-menu">
            <Icon name="attach" size={20} />
          </button>
        ) : (
          <button ref={tp.btnRef} type="button" className="p2-ob" onClick={() => tp.setMenu(!tp.menu)} title="Текст или данные из файла"
            aria-describedby="ct-fmt" aria-haspopup="menu" aria-expanded={tp.menu} aria-controls="tx-menu" style={{ height: 40 }}>
            <Icon name="attach" size={18} />
            <span>Из файла</span>
          </button>
        )}
        {/* помощник сужает колоду — «.txt или .md» сжимается и гаснет (он и в подсказке кнопки) */}
        {!phone && (
          <span className="hp-wo tx-fmtw">
            <span id="ct-fmt" className={cls("p2-hide-s", show(txOpen && !tp.issue))} style={{ fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap" }}>
              .txt или .md
            </span>
          </span>
        )}
        <FileMenu open={tp.menu} off={tp.deckOff} onPick={tp.pick} onData={tp.pickData} onExample={tp.example} exampleBusy={data.exampleBusy}
          onClose={(back) => {
            tp.setMenu(false);
            if (back) tp.btnRef.current?.focus({ preventScroll: true });
          }} />
        <input ref={tp.dataRef} type="file" accept={DATA_ACCEPT} multiple hidden tabIndex={-1} aria-hidden="true"
          onChange={(e) => {
            const files = Array.from(e.currentTarget.files ?? []);
            e.currentTarget.value = "";
            if (files.length) tp.onFiles(files);
          }} />
        <input ref={tp.inputRef} type="file" accept={TEXT_ACCEPT} hidden tabIndex={-1} aria-hidden="true"
          onChange={(e) => {
            const f = e.currentTarget.files?.[0];
            e.currentTarget.value = ""; // тот же файл ещё раз — снова событие change
            if (f) void tp.onFile(f);
          }} />
      </div>
      <span style={{ flex: 1, minWidth: 0 }} />
      {/* колода уже (помощник) — подсказка короче и меняет формулировку на месте: «Готовый текст — агент разложит его по
          слайдам», в тесной колоде (1280) — «Это готовый текст»; целиком — в подсказке */}
      <p className={cls("p2-in p2-hide-s tx-top", show(top))} title={topText}
        style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0, margin: 0, fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272", whiteSpace: "nowrap", animationDelay: "80ms" }}>
        <span className="hp-sw tx-tops">
          <span className="hp-wo"><Icon name="info" size={16} /><span>{topText}</span></span>
          <span className="hp-no"><Icon name="info" size={16} /><span>{readyShort(wrap) ? "Это готовый текст" : "Готовый текст — агент разложит его по слайдам"}</span></span>
        </span>
      </p>
      {closed && (
        <div className="p2-in tx-closed" style={{ display: "flex", alignItems: "center", gap: 24, minWidth: 0 }}>
          <span className={pv.empty ? "p2-muted" : undefined}
            style={{ minWidth: 0, maxWidth: 480, fontSize: 15, fontWeight: 600, lineHeight: "24px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {pv.text}
          </span>
          <button type="button" className="p2-ob" onClick={() => dispatch({ type: "open", step: "text" })} style={{ flex: "none", height: 40 }}>Изменить</button>
        </div>
      )}
    </>
  );
}

/** Идёт ли чтение — для строки о ходе, которая гаснет вместе с его концом. Чтение кончилось — «идёт» держится ещё
 *  время ухода (240 мс, `p2-off`), строка успевает погаснуть со спиннером и «Читаю…»; не погасла (осталась без чтения) —
 *  дальше показывает как есть. */
function useBusyHeld(busy: boolean): boolean {
  const [held, setHeld] = useState(busy);
  useEffect(() => {
    if (busy) return setHeld(true);
    const t = window.setTimeout(() => setHeld(false), 240);
    return () => window.clearTimeout(t);
  }, [busy]);
  return busy || held;
}

/** Строки текста в копии поля: `line(i)` — номер строки, на которой стоит символ `i` (0…n, n — место за последним
 *  символом, там встаёт курсор в конце); не убывает по `i`. `lh` — высота строки, `pad` — отступ текста сверху,
 *  `height` — высота окна поля (clientHeight), `max` — предел прокрутки. */
export interface CopyLines {
  n: number;
  line(i: number): number;
  lh: number;
  pad: number;
  height: number;
  max: number;
}

/** Место верха поля в тексте: символ, с которого начинается первая видимая строка, и на сколько пикселей эта строка уже
 *  ушла вверх. Копии разной ширины переносят строки по-разному — общее у них только место в тексте. */
export interface TextSpot {
  at: number;
  dy: number;
}

/** Первый символ строки `k`: наименьший `i` из 0…n, у которого `line(i) >= k` (двоичный поиск — для длинного текста
 *  хватает двух десятков замеров). */
export function lineStart(c: Pick<CopyLines, "n" | "line">, k: number): number {
  if (k <= 0) return 0;
  let lo = 0, hi = c.n;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (c.line(mid) >= k) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}

/** Где в тексте верх поля, прокрученного на `scrollTop`. */
export function spotAt(c: CopyLines, scrollTop: number): TextSpot {
  const y = Math.max(0, scrollTop - c.pad);
  const k = Math.floor(y / c.lh);
  return { at: lineStart(c, k), dy: y - k * c.lh };
}

/** Строка курсора `caret` видна целиком в поле, прокрученном на `scrollTop`. */
export function caretShown(c: CopyLines, scrollTop: number, caret: number): boolean {
  const top = c.pad + c.line(caret) * c.lh;
  return top >= scrollTop - 0.5 && top + c.lh <= scrollTop + c.height + 0.5;
}

/** Прокрутка копии, при которой наверху поля — то же место текста: строка с символом `spot.at`, ушедшая вверх на те же
 *  `dy`. `caret` — курсор, который был виден в уходящей копии: он остаётся виден и здесь (широкая строка в узкой копии —
 *  несколько строк, и курсор мог бы уйти под низ поля). */
export function scrollFor(c: CopyLines, spot: TextSpot, caret: number | null = null): number {
  let top = c.pad + c.line(spot.at) * c.lh + spot.dy;
  if (caret !== null) {
    const bottom = c.pad + (c.line(caret) + 1) * c.lh;
    if (bottom > top + c.height) top = bottom - c.height;
  }
  return Math.min(Math.max(0, top), c.max);
}

/** Свойства, от которых зависят переносы строк поля, — двойник берёт их у копии. */
const TWIN_PROPS = [
  "font-family", "font-size", "font-weight", "font-style", "font-stretch", "font-variant", "font-feature-settings", "font-variation-settings",
  "font-kerning", "font-optical-sizing", "letter-spacing", "word-spacing", "line-height", "text-transform", "text-indent", "tab-size",
  "white-space", "white-space-collapse", "text-wrap-mode", "text-wrap-style", "overflow-wrap", "word-break", "line-break", "hyphens",
  "text-rendering", "direction", "unicode-bidi",
];

/** Строки копии поля. В textarea строк не видно — их показывает двойник: невидимый блок той же ширины текста и того же
 *  шрифта, в нём номер строки символа — по его прямоугольнику. Копия без раскладки (скрыта в узком окне) — null. */
function copyLines(ta: HTMLTextAreaElement): { lines: CopyLines; drop(): void } | null {
  if (!ta.isConnected || ta.clientHeight === 0) return null;
  const cs = getComputedStyle(ta);
  const px = (v: string) => parseFloat(v) || 0;
  const side = px(cs.paddingLeft) + px(cs.paddingRight), border = px(cs.borderLeftWidth) + px(cs.borderRightWidth);
  const bar = Math.max(0, ta.offsetWidth - ta.clientWidth - border);
  const width = px(cs.width) - (cs.boxSizing === "border-box" ? side + border : 0) - bar;
  const lh = px(cs.lineHeight) || px(cs.fontSize) * 1.2;
  const value = ta.value, n = value.length;
  // двойник строится при первом замере: поле наверху текста и без курсора его не требует
  let twin: { el: HTMLDivElement; text: Text; base: number; range: Range } | null = null;
  const make = () => {
    const el = document.createElement("div");
    for (const p of TWIN_PROPS) {
      const v = cs.getPropertyValue(p);
      if (v) el.style.setProperty(p, v);
    }
    Object.assign(el.style, {
      position: "fixed", left: "-100000px", top: "0", width: `${width}px`, margin: "0", padding: "0", border: "0", boxSizing: "content-box",
      overflow: "hidden", visibility: "hidden", pointerEvents: "none", contain: "layout style",
    });
    // символ нулевой ширины за текстом — место курсора в конце (и строка за последним переводом строки, как в поле)
    const text = document.createTextNode(`${value}\u200b`);
    el.appendChild(text);
    document.body.appendChild(el);
    return { el, text, base: el.getBoundingClientRect().top, range: document.createRange() };
  };
  const memo = new Map<number, number>([[0, 0]]);
  const line = (i: number): number => {
    const at = Math.min(Math.max(0, i), n);
    const known = memo.get(at);
    if (known !== undefined) return known;
    twin ??= make();
    twin.range.setStart(twin.text, at);
    twin.range.setEnd(twin.text, at + 1);
    const r = twin.range.getClientRects()[0];
    // строка — по середине прямоугольника знака: его высота — высота шрифта, а не строки
    const k = r ? Math.max(0, Math.floor((r.top + r.height / 2 - twin.base) / lh)) : line(at - 1);
    memo.set(at, k);
    return k;
  };
  return {
    lines: { n, line, lh, pad: px(cs.paddingTop), height: ta.clientHeight, max: Math.max(0, ta.scrollHeight - ta.clientHeight) },
    drop: () => twin?.el.remove(),
  };
}

/** Две копии поля: колода сузилась или расширилась — копии меняются перекрёстным затуханием. На каждой смене входящая
 *  копия встаёт на то же место текста, что и уходящая (первая видимая строка — та же; в покое скрытая копия могла стоять
 *  где угодно), фокус тут ни при чём: посреди хода обе показывают одно и то же. Курсор стоял в уходящей копии — он
 *  переходит во входящую на то же место (выделение то же) и не уходит из виду, без прокрутки страницы. Смена туда и
 *  обратно без прокрутки между ними возвращает уходящую копию ровно туда, где она стояла. */
function useCopyFocus(active: RefObject<HTMLTextAreaElement>, other: RefObject<HTMLTextAreaElement>, narrow: boolean) {
  const was = useRef(narrow);
  // последняя переданная прокрутка: копия, куда встала, на что и откуда (место текста)
  const last = useRef<{ el: HTMLTextAreaElement; top: number; value: string; spot: TextSpot } | null>(null);
  useLayoutEffect(() => {
    if (was.current === narrow) return;
    was.current = narrow;
    const to = active.current, from = other.current;
    if (!to || !from) return;
    const focused = document.activeElement === from;
    const { selectionStart, selectionEnd, selectionDirection } = from;
    const caret = selectionDirection === "backward" ? selectionStart : selectionEnd;
    if (focused) {
      to.focus({ preventScroll: true });
      to.setSelectionRange(selectionStart, selectionEnd, selectionDirection ?? undefined);
    }
    const src = copyLines(from);
    if (!src) return;
    const dst = copyLines(to);
    try {
      if (!dst) return;
      const prev = last.current;
      // уходящая копия стоит там, куда её поставила прошлая смена, — место текста то же, что тогда (пересчёт с её
      // переносов сдвинул бы его на строку назад при каждой смене)
      const spot = prev && prev.el === from && prev.value === from.value && Math.abs(prev.top - from.scrollTop) < 1 ? prev.spot : spotAt(src.lines, from.scrollTop);
      const keep = focused && caretShown(src.lines, from.scrollTop, caret) ? caret : null;
      to.scrollTop = scrollFor(dst.lines, spot, keep);
      last.current = { el: to, top: to.scrollTop, value: to.value, spot };
    } finally {
      src.drop();
      dst?.drop();
    }
  }, [narrow, active, other]);
}

const LINE: CSSProperties = { display: "flex", alignItems: "center", gap: 8, minWidth: 0, margin: 0, fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#5A6272" };
/** Поле «О чём презентация» (обе копии). */
const TA: CSSProperties = { flex: 1, minHeight: 0, width: "100%", padding: "0 0 24px", border: 0, resize: "none", background: "transparent", fontFamily: "inherit", fontSize: 16, fontWeight: 500, lineHeight: "24px", color: "#0B1220" };
/** Текст строки под полем — одна строка: узкая колода (помощник) сжимает его многоточием, целиком — в подсказке. */
const ONE: CSSProperties = { minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const NOTE_LINE: CSSProperties = { flex: "none", fontSize: 13, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap" };

/** Тело шага 02 (слот `p2`, `#p2-b2`). */
export function TextBody({ tp }: { tp: TextPlate }) {
  const { ui, brief, data } = useApp();
  const { writer } = useWriting();
  const on = ui.screen === "create" && ui.open === "text" && !ui.more;
  const impOn = useImproveOn();
  // «Улучшить готовую»: поле уходит под заметку на её высоту + 16 — в обеих раскладках (высоты — замер двух копий её
  // текста); помощник сужает колоду — сдвиг и рост поля идут той же кривой, что высота заметки (create.css `.tx-fw`)
  const [noteH, setNoteH] = useState<NoteHeights>({ wide: 0, narrow: 0 });
  const iw = improveShift(noteH.wide), inr = improveShift(noteH.narrow || noteH.wide);
  const noteVars = {
    "--tx-sh": `${iw.shift}px`, "--tx-gr": `${iw.grow}px`, "--tx-dsh": `${inr.shift - iw.shift}px`, "--tx-dgr": `${inr.grow - iw.grow}px`, "--tx-grn": `${inr.grow}px`,
    ...(noteH.wide > 0 && { "--tx-nhw": `${noteH.wide}px` }), ...(noteH.narrow > 0 && { "--tx-nhn": `${noteH.narrow}px` }),
  } as CSSProperties;
  // поле — две копии (широкая и узкая) в одном месте: текст не переносится заново посреди хода; активна одна — в неё фокус
  const narrow = useNarrow();
  const otherRef = useRef<HTMLTextAreaElement>(null);
  useCopyFocus(tp.taRef, otherRef, narrow);
  const line = tp.line;
  const issue = tp.issue;
  const busy = !!tp.reading;
  // строка о ходе чтения («Модель не подключена…») встаёт на место подсказки и «Читаю…»; ошибка сильнее неё
  const infoOn = !issue && !!tp.info;
  // с файлами данных строка — о них («бриф — текст по данным»), а не «цифр и таблиц в тексте нет»
  const noFactsWithData = data.cards.length > 0 && line.kind === "facts" && !line.facts;
  const hintOn = !issue && !busy && !infoOn && (line.kind === "topic" || noFactsWithData);
  const readyOn = !issue && !busy && !infoOn && line.kind === "ready";
  const factsOn = !issue && !busy && !infoOn && line.kind === "facts" && !noFactsWithData;
  const busyOn = busy && !infoOn && !issue;
  // гаснущая строка держит своё: разбор, ошибку, имя презентации, строку о ходе
  const facts = useHeld(line.kind === "facts" ? line : null);
  const shown = useHeld(issue);
  const deck = useHeld(tp.reading);
  const note = useHeld(tp.info);
  // строка о ходе, пока гаснет, остаётся такой, какой была: со спиннером и «Читаю…» — чтение кончается на кадр раньше,
  // чем строка уходит, и живое `busy` подменило бы значок и текст прямо в уходе
  const infoBusy = useBusyHeld(busy);
  // «Это тема…» с перечнем — пока колода шире 1300 (morph.ts `hintTail`): в узкой колоде — без перечня, он в подсказке;
  // формулировка меняется на месте (hp-wo / hp-no)
  const wrap = useDeckWrap();
  const tail = hintTail(wrap);
  // файлы с данными: справа от поля — панель «Данные» (дорожка 0 → 400, узкая колода — dataPanel), под полем — цели из
  // текста; поле у́же — стопка его копий c-tad (на сколько у́же в узкой раскладке — от ширины панели)
  const dataOn = data.cards.length > 0;
  const motion = usePanelMotion(data.cards, data.removeCard);
  const panel = dataPanel(wrap);
  const body = useRef<HTMLDivElement>(null);
  const drop = useFilesDrop(body, on && !busy, tp.onFiles);
  const taProps = {
    value: brief, onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => tp.type(e.target.value), style: TA,
  };
  const describedBy = issue ? "ce-err" : factsOn ? "ct-facts" : undefined;
  return (
    <div id="p2-b2" ref={body} className={cls("p2-body", show(on))} style={{ margin: "24px 0 0 192px" }}>
      <div className="tx-b2" style={noteVars}>
        <ImproveNote on={impOn} onHeights={setNoteH} />
        <div className={cls("tx-fw dt-g", impOn && "tx-fw-imp", motion.grid)} style={{ "--dtn": `${panel.narrow}px` } as CSSProperties}>
          <div className={cls("p2-field p2-stag tx-ring", issue && "ce-bad")}
            style={{ display: "flex", flexDirection: "column", height: 244, padding: 24, borderRadius: 24, background: "#FFFFFF" }}>
            <label htmlFor={narrow ? "ct-tan" : "ct-taw"} style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
              <span style={{ fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "#5A6272" }}>О чём презентация</span>
              <span className="p2-taw">
                <span className="hp-tx hp-txf hp-txa" data-tx={dataOn ? "c-tad" : "c-ta"} style={dataOn ? ({ "--hpd": `${panel.hpd}px` } as CSSProperties) : undefined}>
                  <textarea id="ct-taw" ref={narrow ? otherRef : tp.taRef} className="hp-txw p2-ta ct-ta p2-fade" {...taProps}
                    aria-invalid={!!issue} aria-describedby={narrow ? undefined : describedBy} aria-hidden={narrow || undefined} tabIndex={narrow ? -1 : undefined} />
                  <textarea id="ct-tan" ref={narrow ? tp.taRef : otherRef} className="hp-txn p2-ta ct-ta p2-fade" {...taProps}
                    aria-invalid={!!issue} aria-describedby={narrow ? describedBy : undefined} aria-hidden={!narrow || undefined} tabIndex={narrow ? undefined : -1} />
                </span>
                {brief === "" && <TypingHint live={ui.screen === "create"} tw={tp.tw} writer={writer || dataOn} />}
              </span>
            </label>
            <div className="p2-wrap" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, height: 20, marginTop: 16 }}>
              <div className="tx-sw">
                <p className={show(hintOn)} style={LINE} title={dataOn ? HINT_BRIEF : HINT_TOPIC + HINT_TOPIC_TAIL}>
                  <span style={{ display: "flex", flex: "none" }}><Icon name="info" size={16} /></span>
                  {dataOn ? (
                    <span className="hp-sw tx-hsw"><span className="hp-wo">{HINT_BRIEF}</span><span className="hp-no">{HINT_BRIEF_N}</span></span>
                  ) : (
                    <span className="hp-sw tx-hsw"><span className="hp-wo">{HINT_TOPIC}{tail && HINT_TOPIC_TAIL}</span><span className="hp-no">{HINT_TOPIC}</span></span>
                  )}
                </p>
                <p className={show(readyOn)} style={LINE} title={HINT_READY}>
                  <span style={{ display: "flex", flex: "none" }}><Icon name="info" size={16} /></span>
                  <span style={ONE}>{HINT_READY}</span>
                </p>
                <p id="ct-facts" className={show(factsOn)} style={LINE} title={facts?.kind === "facts" && facts.facts ? `В тексте: ${facts.facts}` : NO_FACTS}>
                  <span style={{ display: "flex", flex: "none", color: "#2563EB" }}><Icon name="numbers" size={16} /></span>
                  {facts?.kind === "facts" && facts.facts
                    ? <span style={ONE}>В тексте: <b style={{ fontWeight: 700, color: "#0B1220" }}>{facts.facts}</b></span>
                    : <span style={ONE}>{NO_FACTS}</span>}
                </p>
                <div id="ce-err" className={cls("tx-err", show(!!issue))} style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                  <ErrorLine key={tp.issueSeq} text={shown?.text ?? ""} lines={1} />
                  <button type="button" className={cls("tx-take", shown?.kind !== "empty" && "p2-none")} onClick={tp.take}>
                    Взять пример
                  </button>
                </div>
                <p className={show(busyOn)} role="status" style={{ ...LINE, whiteSpace: "nowrap" }}>
                  <span style={{ display: "flex", flex: "none", color: "#2563EB" }}><Spinner size={16} /></span>
                  <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{deck ? `Читаю презентацию «${templateStem(deck)}»…` : ""}</span>
                </p>
                <p className={show(infoOn)} role="status" title={infoOn && note ? note : undefined} style={{ ...LINE, whiteSpace: "nowrap" }}>
                  <span style={{ display: "flex", flex: "none", color: infoBusy ? "#2563EB" : undefined }}>{infoBusy ? <Spinner size={16} /> : <Icon name="info" size={16} />}</span>
                  <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{infoBusy && deck ? `Читаю презентацию «${templateStem(deck)}»… ${note ?? ""}` : note}</span>
                </p>
              </div>
              {/* у ошибки файла правая часть (счётчик, подсказка) гаснет, но держит своё место: ничего не выскакивает, а ширина
                  строки ошибки не прыгает (длинная — многоточием, целиком — в подсказке). Счётчик без aria-live: он не
                  перебивает чтение с экрана на каждом знаке */}
              <span className={cls("tx-sw tx-swr", show(issue?.kind !== "file"))}>
                <span className={show(!issue)} style={{ ...NOTE_LINE, fontWeight: 600 }}>{charsLabel(brief.length)}</span>
                {/* помощник сужает колоду — подсказка сжимается и гаснет: строке ошибки — вся ширина */}
                <span className="hp-wo tx-fixw"><span className={show(!!issue)} style={{ ...NOTE_LINE, fontWeight: 500 }}>{FIX}</span></span>
              </span>
            </div>
          </div>
          {/* панель «Данные» (V2 `.dt-cell`): закрыта — дорожка 0, клетка обрезает её содержимое */}
          <div className="dt-cell" aria-hidden={!dataOn || undefined}>
            <DataPanel cards={data.cards} motion={motion} />
          </div>
          {/* цели из текста: показывают, что бриф влияет на выбор графика */}
          {motion.goals && (
            <div className={cls("dt-goalw", show(dataOn))}>
              <GoalsBox text={brief} />
            </div>
          )}
        </div>
        <DataZone on={drop.over} count={drop.count} />
      </div>
    </div>
  );
}
