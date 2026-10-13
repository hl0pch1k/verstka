// Карточки колонки результата (R-aside `ra-card`): «Качество», «Как работал агент», «Почему так», «Взгляд дизайнера».
// Каждая открывает лист «Подробнее» на своей вкладке. Данные — resultView: карточки без данных нет, пустых карточек не
// бывает. Сменились вариант или слайд — меняющийся текст проявляется заново (ra-xf 240 мс), сама карточка стоит.
import { useRef } from "react";
import type { SheetTab } from "../deck/geometry";
import { Icon, type IconName } from "../kit/Icon";
import { ScoreRing } from "../kit/ScoreRing";
import type { EyesView, QualityView } from "./resultView";

/** Ключ сменился хотя бы раз: текст уже не первый — он проявляется (ra-xf), а не входит вместе с колонкой. */
export function useChanged(key: string): boolean {
  const first = useRef(key);
  const changed = useRef(false);
  if (key !== first.current) changed.current = true;
  return changed.current;
}

const Go = () => <Icon name="chevron-right" size={16} className="ra-go" />;

export interface AsideCardsData {
  quality: QualityView | null;
  agent: { step: string; text: string; icon: IconName }[];
  why: string | null;
  eyes: EyesView | null;
  /** Текущий слайд (с 1) и вариант — ключи смены текста. */
  slide: number;
  variant: string;
}

export function AsideCards({ data, open }: { data: AsideCardsData; open(tab: SheetTab): void }) {
  const { quality, agent, why, eyes } = data;
  if (!quality && !agent.length && !why && !eyes) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 24 }}>
      {quality && <QualityCard q={quality} variant={data.variant} onOpen={() => open("quality")} />}
      {agent.length > 0 && <AgentCard lines={agent} variant={data.variant} onOpen={() => open("agent")} />}
      {why && <WhyCard text={why} slide={data.slide} k={`${data.variant}/${data.slide}`} onOpen={() => open("why")} />}
      {eyes && <EyesCard e={eyes} slide={data.slide} k={`${data.variant}/${data.slide}`} onOpen={() => open("quality")} />}
    </div>
  );
}

function QualityCard({ q, variant, onOpen }: { q: QualityView; variant: string; onOpen(): void }) {
  const swapped = useChanged(variant);
  return (
    <button type="button" className="ra-card" title={q.title} onClick={onOpen}>
      <span key={variant} className={swapped ? "ra-xf" : undefined} style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <ScoreRing score={q.score} />
        <span style={{ display: "flex", flexDirection: "column", justifyContent: "center", flex: 1, minWidth: 0 }}>
          <span className="p2-sr">Качество: </span>
          {(q.verdict || q.warnings) && (
            <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, fontWeight: 700, lineHeight: "20px", color: "#0B1220", whiteSpace: "nowrap" }}>
              {q.verdict && <span style={q.errors ? { color: "#DC2626" } : undefined}>{q.verdict}</span>}
              {q.verdict && q.warnings && <span style={{ fontWeight: 500, color: "#5A6272" }} aria-hidden="true">·</span>}
              {q.warnings && (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "#B45309" }}>
                  <Icon name="warning" size={14} />{q.warnings}
                </span>
              )}
            </span>
          )}
          {q.figures && (
            <span title={q.figures.title} style={{ fontSize: 13, fontWeight: 500, lineHeight: "20px", color: q.figures.tone === "warn" ? "#B45309" : "#5A6272" }}>
              {q.figures.text}
            </span>
          )}
        </span>
      </span>
    </button>
  );
}

function AgentCard({ lines, variant, onOpen }: { lines: AsideCardsData["agent"]; variant: string; onOpen(): void }) {
  const swapped = useChanged(variant);
  return (
    <button type="button" className="ra-card" onClick={onOpen}>
      <span className="ra-ch"><span className="ra-ct">Как работал агент</span><Go /></span>
      <span key={variant} className={swapped ? "ra-xf" : undefined} style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
        {lines.map((l, i) => (
          <span key={i} title={`${l.step}: ${l.text}`} style={{ display: "grid", gridTemplateColumns: "24px minmax(0, 1fr)", columnGap: 12, alignItems: "start" }}>
            <span className="ra-ri" aria-hidden="true"><Icon name={l.icon} size={14} /></span>
            <span style={{ paddingTop: 2, fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>
              <b style={{ fontWeight: 700, color: "#0B1220" }}>{l.step}</b> {l.text}
            </span>
          </span>
        ))}
      </span>
    </button>
  );
}

function WhyCard({ text, slide, k, onOpen }: { text: string; slide: number; k: string; onOpen(): void }) {
  const swapped = useChanged(k);
  return (
    <button type="button" className="ra-card" onClick={onOpen}>
      <span className="ra-ch">
        <span className="ra-ct">Почему так</span>
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}><span className="ra-cm">Слайд {slide}</span><Go /></span>
      </span>
      <span key={k} className={swapped ? "ra-xf" : undefined} title={text}
        style={{ display: "-webkit-box", marginTop: 8, fontSize: 14, fontWeight: 500, lineHeight: "20px", color: "#0B1220", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
        {text}
      </span>
    </button>
  );
}

const SHOT = { display: "block", width: 80, height: 45, aspectRatio: "16 / 9", objectFit: "cover", borderRadius: 12, boxShadow: "0 0 0 1px rgba(11,18,32,.08)" } as const;
const SHOT_CAP = { fontSize: 12, fontWeight: 600, lineHeight: "16px" } as const;

function EyesCard({ e, slide, k, onOpen }: { e: EyesView; slide: number; k: string; onOpen(): void }) {
  const swapped = useChanged(k);
  return (
    <button type="button" className="ra-card" title={e.title} onClick={onOpen}>
      <span className="ra-ch">
        <span style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span className="ra-ct">Взгляд дизайнера</span>
          {e.tag && <span key={k} className={swapped ? "ra-tag ra-xf" : "ra-tag"}>{e.tag}</span>}
        </span>
        <Go />
      </span>
      <span key={k} className={swapped ? "ra-xf" : undefined} style={{ display: "flex", alignItems: "flex-start", gap: 16, marginTop: 8 }}>
        {e.pics && (
          <span style={{ display: "flex", alignItems: "flex-start", gap: 8, flex: "none" }}>
            <span style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <img src={e.pics.before} alt={`Слайд ${slide} до пересборки`} style={{ ...SHOT, opacity: 0.64 }} />
              <span style={{ ...SHOT_CAP, color: "#5A6272" }}>было</span>
            </span>
            <span style={{ display: "flex", flex: "none", marginTop: 14, color: "#5A6272" }}><Icon name="arrow-right" size={16} /></span>
            <span style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <img src={e.pics.after} alt={`Слайд ${slide} после пересборки`} style={SHOT} />
              <span style={{ ...SHOT_CAP, color: "#0B1220" }}>стало</span>
            </span>
          </span>
        )}
        <span style={{ minWidth: 0, fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>{e.text}</span>
      </span>
    </button>
  );
}
