// Разбор загруженного шаблона (C-analyzing): слева 2×2 — разбираемый файл (скелетон с полосой хода), две первые обложки
// ленты и «Все шаблоны», справа на две колонки — восемь шагов разбора. Разметка — boards/V2.dc.html, `tpRunOn`. Когда
// помощник сужает колоду, вторая дорожка (первая обложка и «Все шаблоны») сжимается до нуля и её плитки гаснут на месте
// (`tp-anl`, create.css): слева файл и вторая обложка, шаги — на двух колонках справа.
// Шаги идут по сообщениям задачи `analyze` (ribbon.ts `analysisSteps`); по окончании разбор гаснет за 240 мс (`tp-out`).
// Неудача — строка в той же коробке: причина по-русски (ribbon.ts `analysisError`) и «Попробовать ещё раз»; если файл
// не принят по типу — повторять нечего, вместо него «Выбрать другой файл».
import type { CSSProperties } from "react";
import { useApp } from "../../store";
import type { TemplateListItem } from "../../types";
import { cls } from "../kit/cls";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { ActTile, moreText, TemplateTile, usePickTemplate } from "./TemplateRibbon";
import { analysisRows, ANALYSIS_STEPS, type AnalysisFacts, type StepState } from "./ribbon";
import { tplLabel } from "../../lib/plain";

const H2: CSSProperties = {
  margin: 0, fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: "28px", letterSpacing: "-0.02em",
  color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
};

export function Analysis({ list, name, fileName, steps, facts, out, error, canRetry, info, onPeek, onGallery, onRetry, onOther, onClose }: {
  /** Шаблоны в порядке ленты (первые два стоят рядом с разбором). */
  list: TemplateListItem[];
  /** Имя шаблона («Northwind Q3») и файла («Northwind Q3.pptx»). */
  name: string; fileName: string;
  steps: StepState[]; facts: AnalysisFacts;
  /** Разбор гаснет (240 мс), затем проявляется лента. */
  out: boolean;
  /** Неудача разбора — текст строки (уже по-русски); null, пока разбор идёт. */
  error: string | null;
  /** С тем же файлом можно ещё раз; нет — файл не принят по типу, нужен другой. */
  canRetry: boolean;
  /** Строка о ходе («Модель не подключена — разберу шаблон по правилам»). */
  info: string | null;
  onPeek(id: string): void; onGallery(): void; onRetry(): void; onOther(): void; onClose(): void;
}) {
  const { templateId } = useApp();
  const pick = usePickTemplate();
  const done = steps.filter((s) => s === "done").length;
  const all = done >= ANALYSIS_STEPS;
  const two = list.slice(0, 2);
  const hid = Math.max(0, list.length - two.length);
  const rows = analysisRows(steps, facts);
  return (
    <>
      <div className={cls("p2-stag p2-in", out && "tp-out")} style={{ animationDelay: "0ms", transitionDelay: "0ms" }} aria-busy={!error && !all}>
        <div className="an-sk">
          {!error && <span className="an-pulse" aria-hidden="true" />}
          {error && <span aria-hidden="true" style={{ position: "absolute", inset: 0, background: "#F3F4F1" }} />}
          <span className="an-skin">
            <span style={{ fontSize: 14, fontWeight: 700, lineHeight: "20px", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{fileName}</span>
            <span className="an-track" role="progressbar" aria-label={`Разбор шаблона «${name}»`} aria-valuemin={0} aria-valuemax={ANALYSIS_STEPS} aria-valuenow={done}>
              <span className="an-fill tp-fill" style={{ transform: `scaleX(${(done / ANALYSIS_STEPS).toFixed(4)})`, background: error ? "#DC2626" : undefined }} />
            </span>
            <span style={{ marginTop: 8, fontSize: 13, fontWeight: 600, lineHeight: "20px", color: error ? "#DC2626" : "#5A6272" }}>
              {error ? "не получилось" : all ? "готово" : "разбираю…"}
            </span>
          </span>
        </div>
        <span className="an-cap" aria-hidden="true" style={{ alignItems: "center" }}>
          <span className="an-line" style={{ width: 112 }} />
          <span className="an-line" style={{ width: 56 }} />
        </span>
      </div>

      {two.map((t, i) => (
        <TemplateTile key={t.template_id} kind="an" t={t} selected={t.template_id === templateId} delay={40 + i * 40} out={out} cut={i === 0}
          onPick={() => pick(t.template_id)} onPeek={() => onPeek(t.template_id)} />
      ))}

      {hid > 0 && (
        <ActTile kind="an" icon="grid" note={[moreText(hid)]} name="Все шаблоны" delay={120} out={out} onClick={onGallery} cut
          label={`Все шаблоны, ${moreText(hid)}`} title={list.slice(two.length).map(tplLabel).join(", ")} />
      )}

      <section className={cls("an-box p2-stag p2-in", out && "tp-out")} aria-labelledby="an-job" aria-live="polite"
        style={{ gridColumn: "3 / span 2", gridRow: "1 / span 2", animationDelay: "160ms", transitionDelay: "160ms" }}>
        {error ? (
          <>
            <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                <h2 id="an-job" style={{ ...H2, flex: 1, minWidth: 0 }} title={`Не получилось разобрать «${name}»`}>Не получилось разобрать шаблон</h2>
                <button type="button" className="p2-rbl pv-rbw" onClick={onClose} aria-label="Закрыть разбор" title="Вернуться к шаблонам" style={{ flex: "none", margin: "-6px 0" }}>
                  <Icon name="x" size={18} />
                </button>
              </div>
              <ErrorLine text={error} lines={6} />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {canRetry ? (
                <>
                  <button type="button" className="p2-ob" onClick={onRetry} style={{ height: 40, padding: "0 16px" }}>
                    <Icon name="refresh" size={16} />
                    <span>Попробовать ещё раз</span>
                  </button>
                  <button type="button" className="p2-gb" onClick={onOther}>Другой файл</button>
                </>
              ) : (
                <button type="button" className="p2-ob" onClick={onOther} style={{ height: 40, padding: "0 16px" }}>
                  <Icon name="upload" size={16} />
                  <span>Выбрать другой файл</span>
                </button>
              )}
            </div>
          </>
        ) : (
          <>
            <h2 id="an-job" style={H2}>Разбираю шаблон «{name}»</h2>
            {info && <p style={{ margin: 0, fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={info}>{info}</p>}
            <ol className="an-steps">
              {rows.map((r, i) => (
                <li key={i} className={cls("an-step", `an-${r.state}`, i === ANALYSIS_STEPS - 1 && "an-last")} aria-current={r.state === "cur" ? "step" : undefined}>
                  <span className="an-dot" aria-hidden="true"><Icon name="check" size={12} /></span>
                  <span className="an-txt">{r.a}{r.b && <b>{r.b}</b>}{r.c}{r.state === "done" && <span className="p2-sr"> — готово</span>}</span>
                  <span className="an-now">{r.state === "cur" ? "сейчас" : ""}</span>
                </li>
              ))}
            </ol>
          </>
        )}
      </section>
    </>
  );
}
