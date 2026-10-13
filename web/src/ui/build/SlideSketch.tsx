// Эскиз слайда в карточке раскадровки: схема формы, которую выбрал дизайнер, в координатах 160×90 — полоска заголовка,
// строки текста, контуры и акцент (#38BDF8 на тёмной плите). Примитивы и формы обложки, этапов, формулы, графика,
// сравнения, текста с формулой, списка, шагов, картинки, карточек и финала — boards/V2.dc.html (`bdData().SK`,
// доска B-sketch) дословно; формы, которых на доске нет (столбцы, полосы, круговая, таблица, числа, цитата, повестка,
// раздел, код, текст), нарисованы теми же примитивами и слоями. Декоративный: подпись карточки говорит то же словами.
import type { CSSProperties } from "react";
import type { SketchKind } from "../../lib/stage";

const rr = (x: number, y: number, w: number, h: number, r: number) =>
  `M${x + r} ${y}H${x + w - r}A${r} ${r} 0 0 1 ${x + w} ${y + r}V${y + h - r}A${r} ${r} 0 0 1 ${x + w - r} ${y + h}H${x + r}A${r} ${r} 0 0 1 ${x} ${y + h - r}V${y + r}A${r} ${r} 0 0 1 ${x + r} ${y}Z`;
const ci = (cx: number, cy: number, r: number) => `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0Z`;
const hl = (x1: number, y: number, x2: number) => `M${x1} ${y}H${x2}`;

/** Слои эскиза: head — полоска заголовка, txt — строки текста, ln — контуры, acc/bar/dot/tint — акцент шаблона. */
interface Shape { head: string; txt: string; ln: string; acc: string; bar: string; dot: string; tint: string }
const sk = (o: Partial<Shape>): Shape => ({ head: "", txt: "", ln: "", acc: "", bar: "", dot: "", tint: "", ...o });

const SK = {
  // ── формы доски (V2 `bdData().SK`)
  cover: sk({ bar: hl(12, 36, 92) + hl(12, 47, 70), txt: hl(12, 62, 60) + hl(12, 71, 36), ln: ci(124, 45, 24), tint: ci(124, 45, 14) }),
  stages: sk({
    head: hl(12, 16, 72),
    ln: hl(28, 44, 57) + hl(65, 44, 94) + hl(102, 44, 131) + ci(61, 44, 4) + ci(98, 44, 4) + ci(135, 44, 4),
    dot: ci(24, 44, 4),
    txt: [24, 61, 98, 135].map((x) => hl(x - 10, 60, x + 10) + hl(x - 6, 68, x + 6)).join(""),
  }),
  formula: sk({
    head: hl(12, 16, 80),
    acc: rr(12, 28, 76, 26, 5) + "M28 33c-3 0-4 2-4 4v8c0 2-1 4-4 4",
    txt: hl(34, 41, 78) + hl(100, 32, 148) + hl(100, 40, 140) + hl(100, 48, 144) + hl(12, 66, 148) + hl(12, 74, 116),
  }),
  graph: sk({
    head: hl(12, 16, 64),
    ln: "M20 24V76H148M54.7 40.7V76M120.4 35.8V76",
    acc: "M24 66C46 34 90 24 144 42",
    tint: "M54.7 76V40.7L62.5 37.8L72 35.3L82.1 33.7L91.5 33.1L101.3 33.3L112.9 34.5L120.4 35.8V76Z",
  }),
  big: sk({ head: hl(12, 16, 96), acc: rr(24, 30, 112, 28, 6) + "M44 36c-3 0-4 2-4 4v8c0 2-1 4-4 4", txt: hl(52, 44, 124) + hl(36, 70, 124) }),
  compare: sk({
    head: hl(12, 16, 84),
    ln: rr(12, 28, 64, 50, 6) + rr(84, 28, 64, 50, 6),
    bar: hl(21, 38, 50) + hl(93, 38, 122),
    txt: hl(21, 50, 67) + hl(21, 58, 59) + hl(21, 66, 63) + hl(93, 50, 139) + hl(93, 58, 131) + hl(93, 66, 135),
  }),
  parts: sk({
    head: hl(12, 16, 88),
    txt: hl(12, 32, 70) + hl(12, 40, 66) + hl(12, 48, 72) + hl(12, 56, 58) + hl(12, 72, 104) + hl(104, 45, 140),
    acc: rr(84, 28, 64, 34, 6) + "M99 37c-3 0-4 2-4 4v8c0 2-1 4-4 4",
  }),
  list: sk({
    head: hl(12, 16, 80),
    dot: ci(16, 32, 2.5) + ci(16, 44, 2.5) + ci(16, 56, 2.5) + ci(16, 68, 2.5),
    txt: hl(25, 32, 120) + hl(25, 44, 134) + hl(25, 56, 108) + hl(25, 68, 126),
  }),
  steps: sk({
    head: hl(12, 16, 64),
    ln: rr(12, 32, 30, 26, 5) + rr(50, 32, 30, 26, 5) + rr(88, 32, 30, 26, 5) + hl(42, 45, 50) + hl(80, 45, 88) + hl(118, 45, 126),
    acc: rr(126, 32, 22, 26, 5),
    tint: rr(126, 32, 22, 26, 5),
    bar: hl(133, 45, 141),
    txt: hl(19, 45, 35) + hl(57, 45, 73) + hl(95, 45, 111) + hl(12, 70, 96),
  }),
  pic: sk({
    ln: rr(12, 12, 68, 66, 6),
    acc: "M18 70L34 50L46 62L56 52L74 70",
    dot: ci(62, 28, 5),
    head: hl(92, 20, 140),
    txt: hl(92, 34, 148) + hl(92, 42, 142) + hl(92, 50, 146) + hl(92, 58, 128),
  }),
  cards: sk({
    head: hl(12, 16, 96),
    ln: rr(12, 28, 40, 50, 6) + rr(60, 28, 40, 50, 6) + rr(108, 28, 40, 50, 6),
    dot: ci(22, 38, 3) + ci(70, 38, 3) + ci(118, 38, 3),
    txt: hl(20, 52, 44) + hl(20, 60, 40) + hl(68, 52, 92) + hl(68, 60, 88) + hl(116, 52, 140) + hl(116, 60, 136),
  }),
  final: sk({ bar: hl(36, 38, 124), txt: hl(48, 52, 112) + hl(60, 60, 100), dot: ci(70, 72, 2) + ci(80, 72, 2) + ci(90, 72, 2) }),

  // ── формы приложения, которых нет на доске, — теми же слоями
  bars: sk({
    head: hl(12, 16, 64),
    ln: "M20 24V76H148",
    tint: rr(32, 52, 14, 24, 2) + rr(56, 40, 14, 36, 2) + rr(80, 46, 14, 30, 2) + rr(104, 32, 14, 44, 2) + rr(128, 56, 14, 20, 2),
    acc: rr(32, 52, 14, 24, 2) + rr(56, 40, 14, 36, 2) + rr(80, 46, 14, 30, 2) + rr(104, 32, 14, 44, 2) + rr(128, 56, 14, 20, 2),
  }),
  hbars: sk({
    head: hl(12, 16, 64),
    ln: "M28 26V78",
    tint: rr(28, 30, 96, 8, 2) + rr(28, 42, 72, 8, 2) + rr(28, 54, 112, 8, 2) + rr(28, 66, 52, 8, 2),
    acc: rr(28, 30, 96, 8, 2) + rr(28, 42, 72, 8, 2) + rr(28, 54, 112, 8, 2) + rr(28, 66, 52, 8, 2),
    txt: hl(12, 34, 20) + hl(12, 46, 20) + hl(12, 58, 20) + hl(12, 70, 20),
  }),
  pie: sk({
    head: hl(12, 16, 64),
    ln: ci(52, 51, 24),
    tint: "M52 51V27A24 24 0 0 1 74.8 58.4Z",
    acc: "M52 51V27A24 24 0 0 1 74.8 58.4Z",
    dot: ci(96, 39, 2.5) + ci(96, 51, 2.5) + ci(96, 63, 2.5),
    txt: hl(104, 39, 144) + hl(104, 51, 136) + hl(104, 63, 140),
  }),
  table: sk({
    head: hl(12, 16, 72),
    ln: rr(12, 28, 136, 50, 5) + hl(12, 40.5, 148) + hl(12, 53, 148) + hl(12, 65.5, 148) + "M57.3 28V78M102.7 28V78",
    tint: "M17 28H143A5 5 0 0 1 148 33V40.5H12V33A5 5 0 0 1 17 28Z",
    txt: hl(20, 47, 44) + hl(65, 47, 88) + hl(110, 47, 136) + hl(20, 59.5, 40) + hl(65, 59.5, 92) + hl(110, 59.5, 130) + hl(20, 72, 46) + hl(65, 72, 84) + hl(110, 72, 138),
  }),
  numbers: sk({
    head: hl(12, 16, 80),
    bar: hl(14, 40, 44) + hl(62, 40, 92) + hl(110, 40, 140),
    txt: hl(14, 54, 48) + hl(14, 62, 40) + hl(62, 54, 96) + hl(62, 62, 88) + hl(110, 54, 144) + hl(110, 62, 136),
  }),
  quote: sk({
    acc: "M18 44c0-6 3-10 8-11 M30 44c0-6 3-10 8-11",
    dot: ci(21, 45, 3) + ci(33, 45, 3),
    txt: hl(48, 36, 140) + hl(48, 45, 132) + hl(48, 54, 124) + hl(48, 70, 84),
  }),
  agenda: sk({
    head: hl(12, 16, 72),
    acc: rr(13, 28, 8, 8, 2) + rr(13, 40, 8, 8, 2) + rr(13, 52, 8, 8, 2) + rr(13, 64, 8, 8, 2),
    tint: rr(13, 28, 8, 8, 2),
    txt: hl(29, 32, 110) + hl(29, 44, 96) + hl(29, 56, 120) + hl(29, 68, 88),
  }),
  section: sk({
    ln: rr(12, 12, 40, 66, 6),
    tint: rr(12, 12, 40, 66, 6),
    bar: hl(64, 40, 92),
    head: hl(64, 52, 140),
    txt: hl(64, 64, 116),
  }),
  code: sk({
    head: hl(12, 16, 72),
    ln: rr(12, 28, 136, 50, 6),
    txt: hl(22, 39, 70) + hl(30, 47, 96) + hl(30, 55, 84) + hl(22, 63, 60),
    acc: "M118 44l-6 6 6 6 M130 44l6 6-6 6",
  }),
  text: sk({
    head: hl(12, 16, 88),
    txt: hl(12, 32, 148) + hl(12, 40, 140) + hl(12, 48, 144) + hl(12, 56, 116),
    bar: hl(12, 70, 44),
  }),
} satisfies Record<string, Shape>;

type ShapeKey = keyof typeof SK;

/** Форма слайда → его эскиз; слайд с формулой рисуется с рамкой формулы. */
export function shapeOf(kind: SketchKind, formula: boolean): ShapeKey {
  if (formula && kind === "text") return "formula";
  if (formula && (kind === "list" || kind === "cards" || kind === "compare")) return "parts";
  switch (kind) {
    case "timeline": return "stages";
    case "line": return "graph";
    case "image": return "pic";
    case "closing": return "final";
    default: return kind;
  }
}

/** Эскиз карточки; `style` — задержка появления (эскизы встают по 60 мс друг за другом, V2 `skDelay`). */
export function SlideSketch({ kind, formula, style }: { kind: SketchKind; formula: boolean; style?: CSSProperties }) {
  const s = SK[shapeOf(kind, formula)];
  return (
    <svg className="bk-sk p2-pop" viewBox="0 0 160 90" aria-hidden="true" style={style}>
      <path d={s.tint} fill="#38BDF8" fillOpacity=".24" />
      <path d={s.ln} fill="none" stroke="rgba(255,255,255,.4)" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
      <path d={s.txt} fill="none" stroke="rgba(255,255,255,.24)" strokeWidth="3" strokeLinecap="round" />
      <path d={s.head} fill="none" stroke="rgba(255,255,255,.4)" strokeWidth="5" strokeLinecap="round" />
      <path d={s.acc} fill="none" stroke="#38BDF8" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d={s.bar} fill="none" stroke="#38BDF8" strokeWidth="5" strokeLinecap="round" />
      <path d={s.dot} fill="#38BDF8" />
    </svg>
  );
}
