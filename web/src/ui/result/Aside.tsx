// Правая колонка результата (R-aside «Правая колонка целиком»): название, «шаблон · N слайдов · когда», оценка (88/72),
// варианты с оценками, «Скачать PowerPoint», «PDF» и «Изменить текст», карточки и ссылки «План / Шаблон / Файлы».
// Колонка прокручивается внутри с мягким краем (p2-fade), появляется p2-in на обёртке. Та же колонка с карточкой
// «Изображение» (R-picture, V2 `rt-pcol`) открыта у своего конца (`bottom`: column-reverse, края мягкие всегда) и
// лежит поверх обычной. Высота — рабочей области (548 под уведомлением, 612 без него: ResultPlate передаёт её в `style`).
import type { CSSProperties, ReactNode } from "react";
import type { SheetTab } from "../deck/geometry";
import { cls } from "../kit/cls";
import { Icon, type IconName } from "../kit/Icon";
import { Segmented } from "../kit/Segmented";
import { useChanged } from "../kit/useChanged";
import { AsideCards, type AsideCardsData } from "./AsideCards";

const UNB = "'Unbounded','Manrope',sans-serif";

export interface AsideData {
  title: string;
  line: string;
  /** Оценка текущего варианта; null — её нет (каркас без текста), числа нет. */
  score: number | null;
  variants: { key: string; label: string; score: number | null; title?: string }[];
  variant: string;
  /** Ссылки на файлы варианта и имя, под которым они скачиваются (без расширения). */
  pptx: string | null;
  pdf: string | null;
  fileBase: string;
  /** Подсказка «Скачать PowerPoint»: «Вариант 1 · Структурный». */
  pptxTitle: string;
  cards: AsideCardsData;
}

const LINKS: { tab: SheetTab; label: string; icon: IconName }[] = [
  { tab: "plan", label: "План", icon: "plan" },
  { tab: "template", label: "Шаблон", icon: "template" },
  { tab: "files", label: "Файлы", icon: "folder-down" },
];

export function Aside({ d, onVariant, onEditText, onNew, open, id, className, enter = true, bottom, extra, hidden, style }: {
  d: AsideData;
  onVariant(key: string): void;
  onEditText(): void;
  /** «Новая презентация»: «Создать» с чистым листом (useGoHome) — в полном виде, как в компактном. */
  onNew?(): void;
  open(tab: SheetTab): void;
  id?: string;
  className?: string;
  /** Колонка входит лесенкой p2-in (обычная); колонка «Изображение» проявляется сама. */
  enter?: boolean;
  /** Открыта у конца (карточка «Изображение» и ссылки видны сразу). */
  bottom?: boolean;
  /** Карточка после карточек колонки («Изображение»). */
  extra?: ReactNode;
  /** Колонку закрывает другая (панель замечаний, колонка «Изображение»): для чтения с экрана её нет. */
  hidden?: boolean;
  style?: CSSProperties;
}) {
  // другой вариант — его оценка проявляется заново
  const swapped = useChanged(d.variant);
  const second = [
    d.pdf && (
      <a key="pdf" className="p2-ob" href={d.pdf} download={`${d.fileBase}.pdf`}>
        <Icon name="file" size={18} />
        <span>PDF</span>
      </a>
    ),
    <button key="edit" type="button" className="p2-ob" onClick={onEditText} title="Изменить текст или шаблон">
      <Icon name="pen" size={18} />
      <span>Изменить текст</span>
    </button>,
    onNew && (
      <button key="new" type="button" className="p2-ob ra-new" onClick={onNew} title="Новая презентация: чистый лист на «Создать», шаблон остаётся">
        <Icon name="plus" size={18} />
        <span>Новая презентация</span>
      </button>
    ),
  ].filter(Boolean);
  // «Новая презентация» — во всю ширину под остальными (ra-new в result.css)
  const cols = Math.max(1, second.length - (onNew ? 1 : 0));
  const content = <>
    {/* длинное название — две строки и многоточие, целиком — в подсказке */}
    <h1 className="ra-h1" title={d.title} style={{
      margin: 0, fontFamily: UNB, fontWeight: 600, fontSize: 40, lineHeight: "48px", letterSpacing: "-0.03em", color: "#0B1220",
      display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden", overflowWrap: "anywhere",
    }}>{d.title}</h1>
    <p className="ra-line" style={{ margin: "8px 0 0", fontSize: 15, fontWeight: 500, lineHeight: "24px", color: "#5A6272" }}>{d.line}</p>
    {d.score !== null && (
      <div className="ra-scr" style={{ display: "flex", alignItems: "flex-end", gap: 16, height: 72, marginTop: 32 }}>
        <span key={d.variant} className={swapped ? "ra-xf ra-scn" : "ra-scn"}
          style={{ fontFamily: UNB, fontWeight: 700, fontSize: 88, lineHeight: "72px", letterSpacing: "-0.04em", color: "#0B1220" }}>{d.score}</span>
        <span style={{ display: "flex", flexDirection: "column", paddingBottom: 4 }}>
          <span style={{ fontSize: 15, fontWeight: 700, lineHeight: "24px", color: "#0B1220" }}>из 100</span>
          <span style={{ fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>оценка качества</span>
        </span>
      </div>
    )}
    {/* один вариант — выбирать не из чего */}
    {d.variants.length > 1 && (
      <Segmented label="Вариант оформления" value={d.variant} onPick={onVariant} className="ra-segs" style={{ marginTop: 24 }}
        items={d.variants.map((v) => ({
          key: v.key,
          title: v.title,
          label: (
            <span className="ra-vg">
              <span>{v.label}</span>
              {v.score !== null && <span className="p2-rsc">{v.score}</span>}
            </span>
          ),
        }))} />
    )}
    {d.pptx && (
      <a className="p2-cta p2-cta-flat" href={d.pptx} download={`${d.fileBase}.pptx`} title={d.pptxTitle} style={{ width: "100%", marginTop: 24 }}>
        <Icon name="download" size={20} />
        <span>Скачать PowerPoint</span>
      </a>
    )}
    <div className="ra-acts2" style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gap: 16, marginTop: 16 }}>{second}</div>
    <AsideCards data={d.cards} open={open} />
    {extra && <div className="ra-extra" style={{ marginTop: 8 }}>{extra}</div>}
    <div className="ra-sep" style={{ height: 1, marginTop: 16, background: "rgba(11,18,32,.08)" }} />
    <div className="ra-links" style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8, marginTop: 8 }}>
      {LINKS.map((l) => (
        <button key={l.tab} type="button" className="p2-gb" onClick={() => open(l.tab)}>
          <Icon name={l.icon} size={18} />
          <span>{l.label}</span>
        </button>
      ))}
    </div>
  </>;
  return (
    <aside id={id} className={cls(enter && "p2-in", className)} aria-label={`Презентация «${d.title}»`} aria-hidden={hidden || undefined}
      style={{ minWidth: 0, height: 548, margin: "0 -4px", animationDelay: "240ms", gridArea: "1 / 2", ...style }}>
      {bottom ? (
        <div className="ra-col rp-col p2-fade" style={{ display: "flex", flexDirection: "column-reverse", height: "calc(100% + 24px)", padding: "24px 4px", overflowY: "auto" }}>
          <div className="rp-in" style={{ display: "flex", flexDirection: "column", flex: "none" }}>{content}</div>
        </div>
      ) : (
        <div className="ra-col p2-fade" style={{ display: "flex", flexDirection: "column", height: "100%", padding: "0 4px 24px", overflowY: "auto" }}>{content}</div>
      )}
    </aside>
  );
}
