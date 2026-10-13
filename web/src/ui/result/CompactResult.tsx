// Компактный вид «Результата» (boards/G-helper, G-helper-open; V2 `hp-in`): слой над плитой с той же сеткой, что у
// полного вида, — когда помощник сужает колоду, его шапка встаёт в строку уведомления (48 → 64): название, строка
// «шаблон · слайды · когда», действия-иконки («Скачать PDF», «Изменить текст», «Показать текст», «Новая презентация»)
// и «Скачать PowerPoint»; а в узкой колонке 184 px — варианты столбиком, оценка и итоги проверки. Слайд, листание и
// лента миниатюр — общие с полным видом, их сетка перестраивается вместе с колодой (helper.css). Полный вид гаснет за
// 240 мс, компактный проявляется за 240 мс через 120 мс; закрытие — наоборот, быстрее. В режиме «Замечания» и с
// выбранным изображением колонка шире (320 px): панель замечаний стоит в ней, а карточка «Изображение» — здесь, вместо
// итогов.
import type { ReactNode } from "react";
import { cls } from "../kit/cls";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import type { CheckItem } from "./compact";

const UNB = "'Unbounded','Manrope',sans-serif";
const TONE: Record<CheckItem["tone"], string> = { ok: "#2563EB", warn: "#B45309", error: "#DC2626" };

export interface CompactData {
  title: string;
  line: string;
  /** Строка неудачи результата (на месте строки под названием: уведомления в компактном виде нет). */
  error: string | null;
  score: number | null;
  variants: { key: string; label: string; score: number | null; title?: string }[];
  variant: string;
  pptx: string | null;
  pdf: string | null;
  fileBase: string;
  pptxTitle: string;
  checks: CheckItem[];
  /** У презентации есть написанный агентом текст («Показать текст»). */
  hasText: boolean;
}

export function CompactResult({ d, wide, onVariant, onEditText, onShowText, onNew, card }: {
  d: CompactData;
  /** Колонка шире: режим «Замечания» или карточка «Изображение». */
  wide: boolean;
  onVariant(key: string): void;
  onEditText(): void;
  onShowText(): void;
  onNew(): void;
  /** Карточка «Изображение» на месте итогов (выбрано изображение на слайде); null — нет. */
  card: { shown: boolean; node: ReactNode } | null;
}) {
  return (
    <div className={cls("hp-in", wide && "hp-wide")}>
      <div className="hp-top hp-xf">
        <div className="gh-top p2-in" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, height: 64, animationDelay: "160ms" }}>
          <div style={{ minWidth: 0 }}>
            <h1 title={d.title} style={{ margin: 0, fontFamily: UNB, fontWeight: 600, fontSize: 32, lineHeight: "40px", letterSpacing: "-0.03em", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.title}</h1>
            {d.error
              ? <ErrorLine text={d.error} lines={1} quiet style={{ display: "flex", marginTop: 4 }} />
              : <p title={d.line} style={{ margin: "4px 0 0", fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.line}</p>}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}>
            {d.pdf ? (
              <a className="p2-rbl" href={d.pdf} download={`${d.fileBase}.pdf`} aria-label="Скачать PDF" title="Скачать PDF"><Icon name="file" size={18} /></a>
            ) : (
              <button type="button" className="p2-rbl" disabled aria-label="Скачать PDF" title="PDF для этой презентации нет"><Icon name="file" size={18} /></button>
            )}
            <button type="button" className="p2-rbl" onClick={onEditText} aria-label="Изменить текст" title="Изменить текст или шаблон"><Icon name="pen" size={18} /></button>
            <button type="button" className={cls("p2-rbl", !d.hasText && "rt-nb-off")} onClick={onShowText} aria-haspopup="dialog" aria-label="Показать текст"
              aria-disabled={d.hasText ? undefined : true} title={d.hasText ? "Показать текст презентации" : "Для этой презентации текст недоступен"}>
              <Icon name="list" size={18} />
            </button>
            <button type="button" className="p2-rbl" onClick={onNew} aria-label="Новая презентация" title="Новая презентация"><Icon name="plus" size={18} /></button>
            {d.pptx && (
              <a className="p2-cta" href={d.pptx} download={`${d.fileBase}.pptx`} title={d.pptxTitle} style={{ marginLeft: 8 }}>
                <Icon name="download" size={20} />
                <span>Скачать PowerPoint</span>
              </a>
            )}
          </div>
        </div>
      </div>

      <div className={cls("hp-ncol hp-xf", wide && "hp-xf-off")} aria-hidden={wide || undefined}>
        <div className="p2-in" style={{ display: "flex", flexDirection: "column", minHeight: 0, animationDelay: "200ms" }}>
          <div role="group" aria-label="Вариант оформления" style={{ display: "flex", flexDirection: "column", gap: 4, padding: 4, borderRadius: 24, background: "#F3F4F1" }}>
            {d.variants.map((v) => {
              const on = v.key === d.variant;
              return (
                <button key={v.key} type="button" className={cls("p2-rseg", on && "p2-rseg-on")} aria-pressed={on} onClick={() => onVariant(v.key)} title={v.title}
                  style={{ justifyContent: "space-between", width: "100%", padding: "0 16px" }}>
                  <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{v.label}</span>
                  {v.score !== null && <span className="p2-rsc">{v.score}</span>}
                </button>
              );
            })}
          </div>
          {d.score !== null && (
            <div style={{ display: "flex", flexDirection: "column", marginTop: 24 }}>
              <span key={d.variant} className="ra-xf" style={{ fontFamily: UNB, fontWeight: 700, fontSize: 88, lineHeight: "72px", letterSpacing: "-0.04em", color: "#0B1220" }}>{d.score}</span>
              <span style={{ marginTop: 8, fontSize: 15, fontWeight: 700, lineHeight: "24px", color: "#0B1220" }}>из 100</span>
              <span style={{ fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>оценка качества</span>
            </div>
          )}
          <div style={{ height: 1, marginTop: 24, background: "rgba(11,18,32,.08)" }} />
          <ul style={{ display: "flex", flexDirection: "column", gap: 12, margin: "24px 0 0", padding: 0, listStyle: "none" }}>
            {d.checks.map((c, i) => (
              <li key={i} title={c.title} style={{ display: "flex", alignItems: "flex-start", gap: 12, fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#0B1220" }}>
                <span style={{ display: "flex", flex: "none", color: TONE[c.tone] }}><Icon name={c.icon} size={20} /></span>
                <span className="hp-chk">{c.lead && <b style={{ fontWeight: 700, color: c.tone === "ok" ? undefined : TONE[c.tone] }}>{c.lead}</b>}{c.rest}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {card && <div className={cls("hp-pcol hp-xf", !card.shown && "hp-xf-off")} aria-hidden={card.shown ? undefined : true}>{card.node}</div>}
    </div>
  );
}
