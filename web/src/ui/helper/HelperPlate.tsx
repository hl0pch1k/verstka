// Плита «Помощник» (boards/G-helper, G-helper-open; V2 модуль `hp`): ячейка второй колонки обёртки колоды (0 → 400 px),
// плита 400 px #E9F1FF прижата к правому краю и выходит из-под колоды: край колоды, уходя влево, открывает её, сама
// она доезжает последние 32 px той же кривой (520 мс); закрытую колода накрывает (340 мс), плита уходит вправо
// непрозрачной (helper.css `.hp-help`, reveal). Шапка «Помощник» и ✕, лента с мягким краем (сообщения, полосы задач,
// «печатает…»), подсказки и поле до восьми строк со скрепкой и отправкой. Содержимое входит каскадом по 40 мс (шапка
// 160, сообщения 200…400, подсказки 440, поле 480) — переходом, поэтому каскад повторяется при каждом открытии:
// закрытая плита сбрасывает его невидимо, когда колода её уже закрыла (340 мс). Новое сообщение в открытой ленте
// всплывает само (p2-in).
// Плита смонтирована всегда (закрытая — скрыта): недописанное сообщение и задачи из чата живут, пока она закрыта.
import { useEffect, useLayoutEffect, useRef, useState, type ChangeEvent, type CSSProperties, type KeyboardEvent } from "react";
import { humanError } from "../../lib/errors";
import { smoothScroll } from "../../lib/motion";
import { useApp } from "../../store";
import { charsLabel, fileTextIssue, MAX_TEXT_BYTES, TEXT_ACCEPT, TEXT_EXTS } from "../create/textRules";
import { Arc } from "../kit/Arc";
import { cls } from "../kit/cls";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { useSwap } from "../kit/useSwap";
import { useStale } from "../shell/StaleLine";
import { bubbleBlocks, chipsFor, feedDelay, feedItems, introFor, latestRefreshNote, noteView, placeholderFor, typeset, type FeedJob, type FeedNote } from "./chat";
import { useHelperChat } from "./useHelperChat";

const LINE = 24;
const PAD = 16;
/** Поле растёт до восьми строк, дальше прокручивается (мягкий край сверху). */
const MAX_ROWS = 8;
/** Счётчик знаков — только у длинного текста. */
const COUNT_FROM = 1000;

/** Каскад открытия (G-helper-open): закрытие — без каскада, сброс через 340 мс, когда колода уже закрыла плиту. */
const dl = (open: boolean, ms: number) => `${open ? ms : 340}ms`;

/** Пузырь ответа: абзацы и список (`gh-ul`), русская вёрстка без висячих предлогов. */
function BotText({ text }: { text: string }) {
  const blocks = bubbleBlocks(text);
  return (
    <div className="gh-bot">
      {blocks.map((b, i) => b.kind === "p"
        ? <p key={i} style={{ margin: i ? "4px 0 0" : 0 }}>{typeset(b.text)}</p>
        : <ul key={i} className="gh-ul">{b.items.map((t, k) => <li key={k}>{typeset(t)}</li>)}</ul>)}
    </div>
  );
}

/** Полоса задачи из чата (G-helper `gh-job`): «Меняю презентацию» и проценты; не вышло — красная полоса. */
function JobCard({ job }: { job: FeedJob }) {
  const pct = Math.round(job.progress * 100);
  const failed = job.status === "failed";
  return (
    <div className="gh-job" role="status">
      <div style={{ display: "flex", alignItems: "center", gap: 8, height: 20 }}>
        <span style={{ display: "flex", flex: "none", color: failed ? "#DC2626" : "#2563EB" }}><Icon name={failed ? "alert" : "layers"} size={16} /></span>
        <span style={{ flex: 1, minWidth: 0, fontSize: 14, fontWeight: 700, lineHeight: "20px", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{job.label}</span>
        <span style={{ flex: "none", fontFamily: "'Unbounded','Manrope',sans-serif", fontSize: 14, fontWeight: 600, lineHeight: "20px", letterSpacing: "-0.02em", color: failed ? "#DC2626" : "#2563EB", fontVariantNumeric: "tabular-nums" }}>
          {failed ? "не вышло" : `${pct} %`}
        </span>
      </div>
      <div role="progressbar" aria-label={job.label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
        style={{ position: "relative", height: 4, marginTop: 12, borderRadius: 999, background: "#F3F4F1", overflow: "hidden" }}>
        <span className="p2-bar" style={{ position: "absolute", inset: 0, borderRadius: 999, background: failed ? "#DC2626" : "#2563EB", transformOrigin: "left center", transform: `scaleX(${job.progress.toFixed(3)})` }} />
      </div>
    </div>
  );
}

/** Тихая строка ленты (не ответ помощника): «Это другая презентация — откройте её из «Мои презентации»». Строка о
 *  презентации, которую изменили, а она не перечиталась, — с «Обновить», пока длится несвежесть, о которой сказала она
 *  (store `feedRefresh`; дуга, пока читается); перечиталась — «Презентация на экране обновлена» (смена текста —
 *  перекрёстным затуханием), и чужая несвежесть позже её не «оживляет». */
function NoteLine({ note, latest }: { note: FeedNote; latest: boolean }) {
  const { feedRefresh, generation } = useApp();
  const r = useStale(note.refresh ?? "");
  const live = !!note.refresh && feedRefresh[note.refresh] === note.id;
  const view = noteView(note, { stale: r && note.refresh ? { gid: note.refresh, text: r.text } : null, live, latest, open: generation?.id ?? null });
  // текст и «Обновить» сменяются вместе (затухание 120 мс, проявление 240 мс): уходящая кнопка гаснет со строкой
  const t = useSwap(view.refresh ? `1${view.text}` : `0${view.text}`);
  const held = useRef(r);
  if (r) held.current = r;
  const act = t.shown[0] === "1" ? held.current : null;
  return (
    <p role="status" className="gh-note">
      <span style={{ display: "flex", flex: "none", marginTop: 2, color: "#2563EB" }}><Icon name="info" size={16} /></span>
      <span className={t.cls}>
        {typeset(t.shown.slice(1))}
        {act && (
          <>
            {" "}
            <button type="button" className="gh-act" onClick={act.onRefresh} aria-busy={act.busy || undefined}
              title={act.busy ? "Перечитываю презентацию…" : "Перечитать презентацию"}>
              {act.busy && <Arc size={14} />}
              Обновить
            </button>
          </>
        )}
      </span>
    </p>
  );
}

/** Подсказки под лентой. Новые, появившиеся в открытой ленте после ответа, всплывают сами (p2-in); решение принимается
 *  один раз при появлении — класс не добавляется к уже стоящим (иначе анимация спорила бы с каскадом открытия). */
function Chips({ chips, enter, off, onPick, style }: { chips: string[]; enter: boolean; off: boolean; onPick(c: string): void; style: CSSProperties }) {
  const [anim] = useState(enter);
  return (
    <div className={cls("hp-st", anim && "p2-in")} style={{ display: "flex", flexWrap: "wrap", gap: 8, ...style }}>
      {chips.map((c) => <button key={c} type="button" className="p2-pill" onClick={() => onPick(c)} disabled={off}>{c}</button>)}
    </div>
  );
}

export function HelperPlate() {
  const { ui, dispatch, messages, generation, activeVariant, selectedSlide, templateId, building, healthError } = useApp();
  const open = ui.helper;
  const chat = useHelperChat();
  const [text, setText] = useState("");
  const [fileErr, setFileErr] = useState<string | null>(null);
  const plate = useRef<HTMLElement>(null);
  const feed = useRef<HTMLDivElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [overflow, setOverflow] = useState(false);

  // где человек: результат с презентацией, сборка, «Создать»
  const deck = ui.screen === "result" && !!generation?.variants.length;
  const items = feedItems(messages, chat.jobs, chat.notes);
  const intro = introFor({ building: ui.screen === "build" && building, deck });
  const fixable = !!activeVariant?.audit?.issues.some((i) => i.autofix && i.autofix.action !== "none");
  const chips = chipsFor({
    pending: chat.pending, busy: building || chat.working, empty: messages.length === 0, edited: chat.edited, deck,
    open: deck ? generation?.id ?? null : null, slide: selectedSlide,
    template: !!templateId, fixable,
  });
  const placeholder = placeholderFor({ screen: ui.screen, deck, slide: selectedSlide });

  // новое в открытой ленте всплывает само (p2-in); что было до открытия — входит каскадом вместе с плитой
  const openedAt = useRef(0);
  const introAtOpen = useRef(intro);
  if (open && openedAt.current === 0) {
    openedAt.current = Date.now();
    introAtOpen.current = intro;
  } else if (!open && openedAt.current !== 0) openedAt.current = 0;
  const fresh = (ts: number) => open && ts * 1000 > openedAt.current;

  // лента держит новое на виду; при открытии — сразу у конца, без прокрутки на глазах
  const tail = `${items.length}:${chat.pending}:${chips.join("|")}`;
  const wasOpen = useRef(open);
  useLayoutEffect(() => {
    const el = feed.current;
    if (!el) return;
    const opening = open && !wasOpen.current;
    wasOpen.current = open;
    if (!open) return;
    el.scrollTo({ top: el.scrollHeight, behavior: opening ? "auto" : smoothScroll() });
  }, [tail, open]);

  // открытие: курсор — в поле (плита уже едет); закрытие: фокус из плиты — на пункт шапки
  useEffect(() => {
    if (open) {
      const raf = window.requestAnimationFrame(() => area.current?.focus({ preventScroll: true }));
      return () => window.cancelAnimationFrame(raf);
    }
    if (plate.current?.contains(document.activeElement)) document.getElementById("hp-nav")?.focus({ preventScroll: true });
  }, [open]);

  const close = () => dispatch({ type: "set", patch: { helper: false } });
  // Esc вне полей и слоёв (фокус на странице) тоже закрывает помощника — если поверх колоды ничего не открыто
  const layered = !!(ui.sheet || ui.textLayer || ui.lightbox || ui.sect || ui.tplPreview || ui.tplDelete || ui.pattern !== null);
  useEffect(() => {
    if (!open || layered) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (document.activeElement && document.activeElement !== document.body) return;
      dispatch({ type: "set", patch: { helper: false } });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, layered, dispatch]);

  // поле растёт по строкам до восьми; длиннее — прокручивается с мягким краем сверху
  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    const max = MAX_ROWS * LINE + PAD;
    if (!text) {
      el.style.height = `${LINE + PAD}px`;
      return setOverflow(false);
    }
    el.style.height = "auto";
    const h = el.scrollHeight;
    el.style.height = `${Math.max(LINE + PAD, Math.min(h, max))}px`;
    setOverflow(h > max);
  }, [text]);

  const send = (t: string) => {
    if (healthError) return;
    if (chat.send(t) && t === text) setText("");
    setFileErr(null);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send(text);
    }
  };
  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = ""; // тот же файл ещё раз — снова событие change
    if (!f) return;
    const ext = (f.name.match(/\.[a-z0-9]+$/i)?.[0] ?? "").toLowerCase();
    if (!TEXT_EXTS.includes(ext)) return setFileErr("Нужен текстовый файл .txt или .md");
    if (f.size > MAX_TEXT_BYTES) return setFileErr(`Файл «${f.name}» больше 2 МБ`);
    try {
      const raw = await f.text();
      const bad = fileTextIssue(raw, f.name);
      if (bad) return setFileErr(bad.text);
      const content = raw.replace(/\r\n/g, "\n").trim();
      setText((cur) => (cur.trim() ? `${cur.trimEnd()}\n\n${content}` : content));
      setFileErr(null);
      window.requestAnimationFrame(() => area.current?.focus({ preventScroll: true }));
    } catch (err) {
      setFileErr(humanError(err instanceof Error ? err.message : "", `Не удалось прочитать «${f.name}»`));
    }
  };

  const n = items.length + 1;
  const sendOff = !text.trim() || chat.pending || healthError;
  const st = (ms: number): CSSProperties => ({ transitionDelay: dl(open, ms) });

  return (
    <div className="hp-hcell">
      <aside ref={plate} id="hp-help" className="gh-help hp-help" aria-labelledby="hp-title"
        onKeyDown={(e) => {
          if (e.key !== "Escape" || e.defaultPrevented) return;
          e.preventDefault();
          close();
        }}
        style={{ display: "flex", flexDirection: "column", padding: 24, borderRadius: 40, background: "#E9F1FF", color: "#0B1220" }}>
        {/* шапка: заголовок и крестик на одной оси (центр строки 48) */}
        <div className="hp-st" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, height: 48, flex: "none", ...st(160) }}>
          <h2 id="hp-title" style={{ minWidth: 0, margin: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: "28px", letterSpacing: "-0.02em", color: "#0B1220" }}>Помощник</h2>
          <button type="button" className="p2-rbl gh-x" onClick={close} aria-label="Закрыть помощника" title="Закрыть (Esc)">
            <Icon name="x" size={18} />
          </button>
        </div>

        {/* лента: мягкий край; поле 24 снизу — зона растворения, у поля ввода отступ сверху 0 */}
        <div ref={feed} role="log" className="p2-fade" aria-label="Переписка с помощником"
          style={{ flex: 1, minHeight: 0, overflowY: "auto", margin: "16px -4px 0", padding: "4px 4px 24px", scrollbarWidth: "none" }}>
          <div style={{ display: "flex", flexDirection: "column", justifyContent: "flex-end", gap: 12, minHeight: "100%" }}>
            <div key={intro} className={cls("gh-item gh-l hp-st", open && intro !== introAtOpen.current && "p2-in")} style={st(feedDelay(0, n, open))}>
              <BotText text={intro} />
            </div>
            {items.map((it, i) => {
              const { id, ts } = it.kind === "msg" ? it.msg : it.kind === "job" ? it.job : it.note;
              const user = it.kind === "msg" && it.msg.role === "user";
              return (
                <div key={id} className={cls("gh-item hp-st", user ? "gh-r" : "gh-l", fresh(ts) && "p2-in")} style={st(feedDelay(i + 1, n, open))}>
                  {it.kind === "job" ? <JobCard job={it.job} />
                    : it.kind === "note" ? <NoteLine note={it.note} latest={it.note.id === latestRefreshNote(chat.notes, it.note.refresh)} />
                    : user ? <div className="gh-user">{it.msg.text}</div> : <BotText text={it.msg.text} />}
                </div>
              );
            })}
            {chat.pending && (
              <div className="gh-item gh-l p2-in" role="status" aria-label="Помощник печатает">
                <div className="gh-bot hp-typing">печатает…</div>
              </div>
            )}
            {chips.length > 0 && <Chips key={chips.join("|")} chips={chips} enter={open && messages.length > 0} off={healthError} onPick={send} style={st(440)} />}
          </div>
        </div>

        {text.length > COUNT_FROM && (
          <p aria-live="polite" style={{ margin: "-8px 16px 16px 0", flex: "none", fontSize: 12, fontWeight: 600, lineHeight: "16px", color: "#5A6272", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
            {charsLabel(text.length)}
          </p>
        )}
        {fileErr && <ErrorLine key={fileErr} text={fileErr} lines={2} style={{ flex: "none", margin: "-8px 8px 16px" }} />}
        <div className="hp-st" style={{ flex: "none", ...st(480) }}>
          <div className="gh-comp" style={{ display: "flex", alignItems: "flex-end", gap: 8, padding: 8, borderRadius: 24, background: "#FFFFFF" }}>
            <button type="button" className="p2-rbl" onClick={() => fileRef.current?.click()} aria-label="Вставить текст из файла" title="Вставить текст из файла (.txt, .md — до 2 МБ)">
              <Icon name="attach" size={18} />
            </button>
            <input ref={fileRef} type="file" accept={TEXT_ACCEPT} hidden tabIndex={-1} aria-hidden="true" onChange={(e) => void onFile(e)} />
            <label style={{ display: "flex", flex: 1, minWidth: 0 }}>
              <span className="p2-sr">Сообщение помощнику</span>
              <textarea ref={area} className={cls("gh-ta", overflow && "p2-fade-top")} rows={1} value={text} placeholder={placeholder}
                onChange={(e) => {
                  setText(e.target.value);
                  if (fileErr) setFileErr(null);
                }}
                onKeyDown={onKey}
                style={{ display: "block", width: "100%", height: LINE + PAD, padding: "8px 4px", border: 0, resize: "none", background: "transparent", fontFamily: "inherit", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#0B1220", overflowY: "auto", scrollbarWidth: "none" }} />
            </label>
            <button type="button" className="gh-send" onClick={() => send(text)} disabled={sendOff} aria-label="Отправить"
              title={healthError ? "Нет связи с сервером" : "Отправить (Enter)"}>
              <Icon name="arrow-up" size={18} />
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
}
