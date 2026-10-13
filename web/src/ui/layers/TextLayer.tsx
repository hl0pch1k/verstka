// «Текст презентации» (boards/R-text, V2 `#rt-lay-text`, модуль `rt`): голубой слой поднимается над результатом до
// 160 px — над ним остаётся полоса «04 Результат» плиты результата (ResultPlate), клик по ней закрывает слой. Шапка и
// белая коробка с текстом проявляются лесенкой (p2-ls 120/200 мс); закрытый слой уезжает вниз непрозрачным, с текстом.
// Текст — тот, что агент написал по теме (`generation.writer`), по слайдам в две колонки; предложения с источником
// подчёркнуты пунктиром, клик по ним меняет строку «Источник» внизу коробки. «Скопировать» кладёт текст в буфер — рядом
// строка «Скопировано» (без всплывающих уведомлений); «Изменить» открывает «Создать» с этим текстом и параметрами
// презентации, плита результата уходит вниз. Разбор текста — writerText.ts.
import { Fragment, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { humanError } from "../../lib/errors";
import { errText } from "../../lib/narrate";
import { useApp } from "../../store";
import type { Generation, WriterInfo } from "../../types";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { cls } from "../kit/cls";
import { usePresence } from "../kit/usePresence";
import { deckPreset } from "../result/resultView";
import { useGoDown } from "../result/useGoDown";
import { Layer, lsDelay, useLayerFit } from "./Layer";
import { firstSource, sourceLine, writerByline, writerSlides, writtenText, type TextPiece, type WriterSource } from "./writerText";

/** Сколько стоит строка «Скопировано». */
const COPIED_MS = 2400;
const NO_SOURCES: WriterSource[] = [];

export function TextLayer() {
  const { ui, dispatch, generation, editText } = useApp();
  const goDown = useGoDown();
  const text = ui.screen === "result" ? writtenText(generation?.writer) : null;
  const open = ui.textLayer && !!text;
  const fit = useLayerFit(open);
  // текста больше нет (другая презентация) — флаг снимается, иначе слой вернулся бы сам
  useEffect(() => {
    if (ui.textLayer && !text) dispatch({ type: "set", patch: { textLayer: false } });
  }, [ui.textLayer, text, dispatch]);

  // показанная презентация держится, пока слой уезжает
  const last = useRef<Generation | null>(null);
  if (open && generation) last.current = generation;
  const g = last.current;
  const w = g?.writer ?? null;
  const sources = w?.sources ?? NO_SOURCES;
  const slides = useMemo(() => (w?.text ? writerSlides(w.text, sources) : []), [w, sources]);

  // открылся — подсвечен первый источник (как на доске), строки «Скопировано» нет
  const [sel, setSel] = useState<number | null>(null);
  const [copy, setCopy] = useState<{ ok: boolean; err?: string } | null>(null);
  const [seen, setSeen] = useState(false);
  if (open !== seen) {
    setSeen(open);
    if (open) {
      setSel(firstSource(slides));
      setCopy(null);
    }
  }
  const copyTimer = useRef(0);
  useEffect(() => () => window.clearTimeout(copyTimer.current), []);

  const close = () => dispatch({ type: "set", patch: { textLayer: false } });
  const onCopy = () => {
    if (!w?.text) return;
    window.clearTimeout(copyTimer.current);
    const fail = (e: unknown) => setCopy({ ok: false, err: humanError(`Не удалось скопировать: ${errText(e)}`, "Не удалось скопировать") });
    if (!navigator.clipboard?.writeText) return fail(null);
    navigator.clipboard.writeText(w.text).then(() => {
      setCopy({ ok: true });
      copyTimer.current = window.setTimeout(() => setCopy(null), COPIED_MS);
    }, fail);
  };
  // «Изменить»: «Создать» с этим текстом и параметрами презентации (`go` закрывает слой), плита результата — вниз
  const onEdit = () => {
    if (!g || !w?.text) return;
    editText(w.text, deckPreset(g));
    goDown();
  };

  return (
    <Layer id="rt-lay-text" open={open} top={160} z={5} label="Текст презентации" role="dialog" onClose={close}>
      {w && (
        <div style={{ display: "flex", flexDirection: "column", height: 572 }}>
          {/* колода уже (помощник): подпись встаёт под заголовок, «Скопировать» в тесной колоде — значок; шапка
              перестраивается перекрёстным затуханием (useLayerFit, `data-fit` шапки — result.css) */}
          <div className={cls("rt-hd", fit.cls)} data-fit={fit.shown} style={{ flex: "none" }}>
          <div className="p2-hrow p2-ls" style={{ ...lsDelay(120), display: "flex", alignItems: "center", gap: 24, height: 64 }}>
            <div className="rt-head" style={{ display: "flex", alignItems: "center", gap: 24, minWidth: 0 }}>
              <h2 className="p2-ttl" style={{ flex: "none", margin: 0, color: "#0B1220" }}>Текст презентации</h2>
              <Byline w={w} />
            </div>
            <span style={{ flex: 1, minWidth: 0 }} />
            <div className="rt-acts" style={{ display: "flex", alignItems: "center", gap: 16, flex: "none" }}>
              <CopyLine copy={copy} />
              <button type="button" className="p2-ob rt-copy" onClick={onCopy} aria-label="Скопировать" title="Скопировать текст" style={{ flex: "none", height: 40 }}>
                <Icon name="copy" size={18} />
                <span>Скопировать</span>
              </button>
              <button type="button" className="p2-cta" onClick={onEdit} title="Открыть этот текст на шаге «Текст» и собрать заново" style={{ flex: "none" }}>
                <Icon name="pen" size={20} />
                <span>Изменить</span>
              </button>
              <button type="button" className="p2-rbl rt-x" onClick={close} aria-label="Закрыть" title="Закрыть (Esc)" style={{ flex: "none" }}>
                <Icon name="x" size={18} />
              </button>
            </div>
          </div>
          </div>

          <div className="p2-ls" style={{ ...lsDelay(200), display: "flex", flexDirection: "column", flex: 1, minHeight: 0, marginTop: 24, borderRadius: 24, background: "#FFFFFF", overflow: "hidden" }}>
            <div className="rt-scroll p2-fade-top" tabIndex={0} role="region" aria-label="Текст по слайдам" style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: 24 }}>
              <div className="rt-grid" style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "24px 48px" }}>
                {slides.map((s, i) => (
                  <div key={i}>
                    {s.n !== null && (
                      <p style={{ margin: 0, fontSize: 15, fontWeight: 700, lineHeight: "24px", color: "#0B1220" }}>
                        Слайд {s.n}.{s.title && <> <span style={{ fontWeight: 600, color: "#5A6272" }}>{s.title}</span></>}
                      </p>
                    )}
                    {s.lines.map((line, j) => (
                      <p key={j} style={{ margin: j === 0 && s.n !== null ? "4px 0 0" : 0, fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#0B1220", overflowWrap: "anywhere" }}>
                        {line.map((p, k) => <Piece key={k} p={p} on={p.src !== null && p.src === sel} onPick={setSel} />)}
                      </p>
                    ))}
                  </div>
                ))}
              </div>
            </div>
            <SourceRow w={w} sources={sources} sel={sel} />
          </div>
        </div>
      )}
    </Layer>
  );
}

/** «Написал агент по статье «Интеграл» из Википедии»: названия статей — ссылки. */
function Byline({ w }: { w: WriterInfo }) {
  const by = writerByline(w);
  return (
    <p className="rt-sub" style={{ minWidth: 0, margin: 0, fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
      {by.lead}{" "}
      {by.pages.map((p, i) => (
        <Fragment key={`${p.url}-${i}`}>
          {i > 0 && (i === by.pages.length - 1 ? " и " : ", ")}
          <a className="rt-a" href={p.url} target="_blank" rel="noopener noreferrer">«{p.title}»</a>
        </Fragment>
      ))}
      {by.tail && ` ${by.tail}`}
    </p>
  );
}

/** Кусок строки: без источника — просто текст; с источником — пунктир, клик (Enter, пробел) выбирает его источник. */
function Piece({ p, on, onPick }: { p: TextPiece; on: boolean; onPick(k: number): void }) {
  if (p.src === null) return <>{p.text}</>;
  const k = p.src;
  const onKey = (e: KeyboardEvent<HTMLSpanElement>) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    onPick(k);
  };
  return (
    <span className={cls("rt-s", on && "rt-s-on")} role="button" tabIndex={0} aria-pressed={on} onClick={() => onPick(k)} onKeyDown={onKey}>
      {p.text}
    </span>
  );
}

/** Строка рядом с «Скопировать»: «Скопировано» проявляется и гаснет; неудача — красная строка, пока её не сменит
 *  следующая попытка. */
function CopyLine({ copy }: { copy: { ok: boolean; err?: string } | null }) {
  const ok = usePresence(!!copy?.ok, 240);
  if (copy && !copy.ok) {
    return (
      <span className="p2-in" style={{ display: "flex", minWidth: 0, maxWidth: 320 }}>
        <ErrorLine text={copy.err ?? "Не удалось скопировать"} lines={1} />
      </span>
    );
  }
  if (!ok.mounted) return null;
  return (
    <p className={cls("rt-st", ok.shown && "rt-st-on")} role="status">
      <Icon name="check-circle" size={20} />
      <span>Скопировано</span>
    </p>
  );
}

/** Строка «Источник» внизу коробки: предложение статьи, из которого взято выбранное, и ссылка на него. */
function SourceRow({ w, sources, sel }: { w: WriterInfo; sources: WriterSource[]; sel: number | null }) {
  const line = sourceLine(w, sources, sel);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16, height: 64, padding: "0 16px 0 24px", flex: "none", borderTop: "1px solid rgba(11,18,32,.08)" }}>
      <span style={{ display: "flex", flex: "none", color: "#2563EB" }}><Icon name="book" size={20} /></span>
      <p aria-live="polite" title={line.quote}
        style={{ flex: 1, minWidth: 0, margin: 0, fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        <span style={{ fontWeight: 700 }}>Источник:</span> {line.quote}
      </p>
      {line.href && (
        <a className="p2-gb" href={line.href} target="_blank" rel="noopener noreferrer" title={line.title} style={{ flex: "none", textDecoration: "none" }}>
          <span>{line.label}</span>
          <Icon name="external" size={16} />
        </a>
      )}
    </div>
  );
}
