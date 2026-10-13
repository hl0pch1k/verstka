// Плита 02 «Текст» (C-text, C-improve, C-errors): в заголовке — «Из файла» с подписью «.txt или .md» и меню выбора,
// справа подсказка о готовом тексте, на свёрнутом шаге — тема в кавычках и «Изменить»; тело `#p2-b2` — поле «О чём
// презентация» с печатающейся подсказкой, строкой под полем (подсказка агента, разбор текста, ошибка, чтение
// презентации) и счётчиком знаков, над полем в «Улучшить готовую» — заметка об исходной презентации. Разметка —
// boards/V2.dc.html, плита 02 и модуль tx. Строки под полем сменяются перекрёстным затуханием (p2-on / p2-off: уход
// 240 мс, вход 360 мс через 120 мс) и, пока гаснут, держат своё содержимое.
import { useCallback, useEffect, useRef, useState, type CSSProperties, type MutableRefObject, type RefObject } from "react";
import { useApp } from "../../store";
import { SAMPLE_BRIEF } from "../../lib/createForm";
import { humanError } from "../../lib/errors";
import { templateStem } from "../../lib/templateFiles";
import type { ImproveSource } from "../../types";
import { cls } from "../kit/cls";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { Spinner } from "../kit/Spinner";
import { FileMenu, type FilePick } from "./FileMenu";
import { ImproveNote, useHeld, useImproveOn, useModelOn } from "./ImproveNote";
import {
  charsLabel, DECK_ACCEPT, deckError, fileKind, improveShift, MAX_TEXT_BYTES, TEXT_ACCEPT, textError, textLine, textPreview, TW, TW0, TW_FIRST_MS,
  TW_WAKE_MS, twBlink, twStep, twText, type TextIssue, type Tw,
} from "./textRules";

const show = (on: boolean) => (on ? "p2-on" : "p2-off");

const HINT_TOPIC = "Это тема — агент напишет полный текст: ключевые факты, даты, формулы с пояснениями";
const NO_FACTS = "Цифр и таблиц в тексте нет — слайды будут из формулировок";
const FIX = "Вставьте готовый текст или загрузите .txt и .md";

/** Кто пишет текст: `writer` — агент распишет тему (сервер в режиме writer и модель подключена: строка «Это тема —
 *  агент напишет…»); `writes` — модель пишет тексты слайдов («…и допишет недостающее», иначе «…без переписывания»).
 *  Переключатель «Модель пишет тексты» шага 03 сузит оба. */
export function useWriting(): { writer: boolean; writes: boolean } {
  const { health } = useApp();
  const modelOn = useModelOn();
  return { writer: !!health?.writer && modelOn, writes: modelOn };
}

/** Состояние шага на обе части плиты (заголовок и тело): меню, выбор файла, чтение презентации, ошибка у поля,
 *  печатающаяся подсказка. Одно на приложение — его создаёт AppShell. */
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
  /** Ошибка у поля: своя (`textIssue` — правила, файл) или неудача чтения презентации (строка области «Текст»). */
  issue: TextIssue | null;
  /** Номер ошибки: новая ошибка — новая строка (её `role=alert` читается заново). */
  issueSeq: number;
  /** Место печатающейся подсказки: «Взять пример» берёт её фразу, а очищенное поле продолжает с того же места. */
  tw: MutableRefObject<{ s: Tw; started: boolean }>;
  /** Ввод в поле. */
  type(v: string): void;
  /** «Взять пример»: тема из подсказки (V2 `txTake`). */
  take(): void;
}

export function useTextPlate(): TextPlate {
  const {
    ui, dispatch, brief, setBrief, textIssue, setTextIssue, notices, clearNotice, uploadTemplate, templateId,
    composerText, takeComposerText, improveSource, takeImproveSource,
  } = useApp();
  const [menu, setMenu] = useState(false);
  const [reading, setReading] = useState<string | null>(null);
  const lastDeck = useRef("");
  const btnRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
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
  const live = useRef<{ tpl: string | null } | null>(null);
  useEffect(() => {
    if (improveSource && improveSource !== applied.current) {
      applied.current = improveSource;
      live.current = { tpl: improveSource.template_id ?? templateId };
      setBrief(improveSource.brief);
      return;
    }
    if (!ui.improve) {
      live.current = null;
      if (improveSource) takeImproveSource();
      return;
    }
    const l = live.current;
    if (l && (!brief.trim() || templateId !== l.tpl)) dispatch({ type: "set", patch: { improve: false } });
  }, [improveSource, ui.improve, brief, templateId, setBrief, takeImproveSource, dispatch]);

  // шаг свернулся или ушёл с экрана — меню закрывается
  const txOpen = ui.screen === "create" && ui.open === "text" && !ui.more;
  useEffect(() => {
    if (!txOpen) setMenu(false);
  }, [txOpen]);

  const readDeck = useCallback((f: File) => {
    lastDeck.current = f.name;
    setReading(f.name);
    setTextIssue(null);
    clearNotice("text");
    void uploadTemplate(f, true, true).finally(() => setReading(null));
  }, [uploadTemplate, setTextIssue, clearNotice]);

  const onFile = useCallback(async (f: File) => {
    setMenu(false);
    const bad = textError("", f);
    if (bad) return setTextIssue(bad);
    if (fileKind(f.name) === "deck") return readDeck(f);
    if (f.size > MAX_TEXT_BYTES) return setTextIssue({ kind: "file", text: `Файл «${f.name}» больше 2 МБ` });
    try {
      const t = (await f.text()).replace(/\r\n/g, "\n").trim();
      if (!t) return setTextIssue({ kind: "file", text: `Файл «${f.name}» пустой` });
      replace(t);
    } catch (e) {
      setTextIssue({ kind: "file", text: humanError(e instanceof Error ? e.message : "", `Не удалось прочитать «${f.name}»`) });
    }
  }, [readDeck, replace, setTextIssue]);

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
  }, [setBrief]);

  const take = useCallback(() => {
    replace(TW[tw.current.s.i] ?? TW[0]);
    taRef.current?.focus({ preventScroll: true });
  }, [replace]);

  // проверка перед сборкой (пусто, коротко) поднимает шаг «Текст» и ставит курсор в поле
  useEffect(() => {
    if (textIssue && (textIssue.kind === "empty" || textIssue.kind === "short")) taRef.current?.focus({ preventScroll: true });
  }, [textIssue]);

  const notice = notices.text?.kind === "error" ? notices.text.text : null;
  const issue: TextIssue | null = textIssue ?? (notice ? { kind: "file", text: deckError(notice, lastDeck.current) } : null);
  const seq = useRef({ key: null as string | null, n: 0 });
  const key = issue ? `${issue.kind}:${issue.text}` : null;
  if (key !== seq.current.key) seq.current = { key, n: key ? seq.current.n + 1 : seq.current.n };

  return { menu, setMenu, btnRef, inputRef, taRef, pick, onFile, reading, issue, issueSeq: seq.current.n, tw, type, take };
}

const reducedMotion = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Печатающаяся подсказка поверх пустого поля (`p2-tph`) с курсором `p2-caret` — ритм V2 `twTick` (`twStep`). Идёт,
 *  пока поле пустое и открыт «Создать»; поле очистили — продолжает через 400 мс с того же места (V2 `twWake`). При
 *  «уменьшить движение» стоит первая фраза. */
function TypingHint({ live, tw }: { live: boolean; tw: MutableRefObject<{ s: Tw; started: boolean }> }) {
  const [s, setS] = useState(tw.current.s);
  useEffect(() => {
    if (!live || reducedMotion()) return;
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
  }, [live, tw]);
  return (
    <span className="p2-tph" aria-hidden="true">
      {twText(s)}
      <span className={cls("p2-caret", twBlink(s) && "p2-caret-blink")} />
    </span>
  );
}

/** Заголовок плиты 02 справа (слот `h2`). */
export function TextHead({ tp }: { tp: TextPlate }) {
  const { ui, dispatch, brief } = useApp();
  const { writer, writes } = useWriting();
  const impOn = useImproveOn();
  const create = ui.screen === "create";
  const txOpen = create && ui.open === "text" && !ui.more;
  const closed = create && ui.open === "tpl";
  // готовый текст: агент разложит его по слайдам (V2 `txHintTop`) — не в «Улучшить готовую», не при ошибке
  const top = txOpen && textLine(brief, writer).kind === "facts" && !impOn && !tp.issue && !tp.reading;
  const pv = textPreview(brief);
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
        <button ref={tp.btnRef} type="button" className="p2-ob" onClick={() => tp.setMenu(!tp.menu)} title="Текст из файла .txt или .md"
          aria-describedby="ct-fmt" aria-haspopup="menu" aria-expanded={tp.menu} aria-controls="tx-menu" style={{ height: 40 }}>
          <Icon name="attach" size={18} />
          <span>Из файла</span>
        </button>
        <span id="ct-fmt" className={cls("p2-hide-s", show(txOpen && !tp.issue))} style={{ fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap" }}>
          .txt или .md
        </span>
        <FileMenu open={tp.menu} busy={!!tp.reading} onPick={tp.pick}
          onClose={(back) => {
            tp.setMenu(false);
            if (back) tp.btnRef.current?.focus({ preventScroll: true });
          }} />
        <input ref={tp.inputRef} type="file" accept={TEXT_ACCEPT} hidden tabIndex={-1} aria-hidden="true"
          onChange={(e) => {
            const f = e.currentTarget.files?.[0];
            e.currentTarget.value = ""; // тот же файл ещё раз — снова событие change
            if (f) void tp.onFile(f);
          }} />
      </div>
      <span style={{ flex: 1, minWidth: 0 }} />
      <p className={cls("p2-in p2-hide-s tx-top", show(top))}
        style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0, margin: 0, fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272", whiteSpace: "nowrap", animationDelay: "80ms" }}>
        <span style={{ display: "flex", flex: "none" }}><Icon name="info" size={16} /></span>
        <span>{writes ? "Это готовый текст — агент разложит его по слайдам и допишет недостающее" : "Это готовый текст — агент разложит его по слайдам без переписывания"}</span>
      </p>
      {closed && (
        <div className="p2-in" style={{ display: "flex", alignItems: "center", gap: 24, minWidth: 0 }}>
          <span className={pv.empty ? "p2-muted" : undefined}
            style={{ maxWidth: 480, fontSize: 15, fontWeight: 600, lineHeight: "24px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {pv.text}
          </span>
          <button type="button" className="p2-ob" onClick={() => dispatch({ type: "open", step: "text" })} style={{ height: 40 }}>Изменить</button>
        </div>
      )}
    </>
  );
}

const LINE: CSSProperties = { display: "flex", alignItems: "center", gap: 8, minWidth: 0, margin: 0, fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#5A6272" };
const NOTE_LINE: CSSProperties = { flex: "none", fontSize: 13, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap" };

/** Тело шага 02 (слот `p2`, `#p2-b2`). */
export function TextBody({ tp }: { tp: TextPlate }) {
  const { ui, brief } = useApp();
  const { writer } = useWriting();
  const on = ui.screen === "create" && ui.open === "text" && !ui.more;
  const impOn = useImproveOn();
  const [noteH, setNoteH] = useState(0);
  const { shift, grow } = improveShift(noteH);
  const line = textLine(brief, writer);
  const issue = tp.issue;
  const busy = !!tp.reading;
  const hintOn = !issue && !busy && line.kind === "topic";
  const factsOn = !issue && !busy && line.kind === "facts";
  // гаснущая строка держит своё: разбор, ошибку, имя презентации
  const facts = useHeld(line.kind === "facts" ? line : null);
  const shown = useHeld(issue);
  const deck = useHeld(tp.reading);
  return (
    <div id="p2-b2" className={cls("p2-body", show(on))} style={{ margin: "24px 0 0 192px" }}>
      <div className="tx-b2" style={{ "--tx-sh": `${shift}px`, "--tx-gr": `${grow}px` } as CSSProperties}>
        <ImproveNote on={impOn} onHeight={setNoteH} />
        <div className={cls("tx-fw", impOn && "tx-fw-imp")}>
          <div className={cls("p2-field p2-stag tx-ring", issue && "ce-bad")}
            style={{ display: "flex", flexDirection: "column", height: 244, padding: 24, borderRadius: 24, background: "#FFFFFF" }}>
            <label style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
              <span style={{ fontSize: 13, fontWeight: 600, lineHeight: "20px", color: "#5A6272" }}>О чём презентация</span>
              <span className="p2-taw">
                <textarea ref={tp.taRef} className="p2-ta ct-ta p2-fade" value={brief} onChange={(e) => tp.type(e.target.value)}
                  aria-invalid={!!issue} aria-describedby={issue ? "ce-err" : factsOn ? "ct-facts" : undefined}
                  style={{ flex: 1, minHeight: 0, width: "100%", padding: "0 0 24px", border: 0, resize: "none", background: "transparent", fontFamily: "inherit", fontSize: 16, fontWeight: 500, lineHeight: "24px", color: "#0B1220" }} />
                {brief === "" && <TypingHint live={ui.screen === "create"} tw={tp.tw} />}
              </span>
            </label>
            <div className="p2-wrap" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, height: 20, marginTop: 16 }}>
              <div className="tx-sw">
                <p className={show(hintOn)} style={LINE}>
                  <span style={{ display: "flex", flex: "none" }}><Icon name="info" size={16} /></span>
                  <span>{HINT_TOPIC}</span>
                </p>
                <p id="ct-facts" className={show(factsOn)} style={LINE}>
                  <span style={{ display: "flex", flex: "none", color: "#2563EB" }}><Icon name="numbers" size={16} /></span>
                  {facts?.kind === "facts" && facts.facts
                    ? <span>В тексте: <b style={{ fontWeight: 700, color: "#0B1220" }}>{facts.facts}</b></span>
                    : <span>{NO_FACTS}</span>}
                </p>
                <div id="ce-err" className={cls("tx-err", show(!!issue))} style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                  <ErrorLine key={tp.issueSeq} text={shown?.text ?? ""} lines={1} />
                  <button type="button" className={cls("tx-take", shown?.kind !== "empty" && "p2-none")} onClick={tp.take}>
                    Взять пример
                  </button>
                </div>
                <p className={show(busy)} role="status" style={{ ...LINE, whiteSpace: "nowrap" }}>
                  <span style={{ display: "flex", flex: "none", color: "#2563EB" }}><Spinner size={16} /></span>
                  <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{deck ? `Читаю презентацию «${templateStem(deck)}»…` : ""}</span>
                </p>
              </div>
              <span className="tx-sw tx-swr">
                <span aria-live="polite" className={show(!issue)} style={{ ...NOTE_LINE, fontWeight: 600 }}>{charsLabel(brief.length)}</span>
                <span className={show(!!issue)} style={{ ...NOTE_LINE, fontWeight: 500 }}>{FIX}</span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
