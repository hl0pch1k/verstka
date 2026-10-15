// «Не получилось» (boards/B-failed, V2 `bdFailed`): раскадровка гаснет, на её месте встаёт коробка ошибки — иконка-слои
// с красным знаком, «Не получилось собрать презентацию», причина простыми словами, «Вернуться к тексту» и «Собрать ещё
// раз» (тот же запрос). Появляется pop 360 мс через 120 мс.
// Помощник сужает колоду: поля коробки 48 → 24 (V2 версии 100). Сайт: пока помощник закрыт, коробка — как B-failed при
// любой ширине окна (заголовок в строку, причина до 480, кнопки в ряд). Заголовок и причина, которые в узкой колоде
// переносятся иначе (окно около 1280), — стопки из двух копий постоянной ширины (широкая гаснет, узкая проявляется на
// месте, columns.ts `failText`; их высота на ходу идёт линейно); кнопки, которым в узкой колоде нет места в ряд, встают
// столбиком сдвигом (у каждой — к центру, вторая — под первую) в два такта, чтобы не наехать друг на друга: открытие —
// сначала вторая уходит вниз, затем обе — к центру; закрытие — наоборот (build.css). Коробка подвигает содержимое
// отступом снизу. Ширины и высоты кнопок и копий — замер (постоянные).
import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import type { BuildMorph } from "./columns";
import { failText } from "./columns";

/** Ряд кнопок → столбик: сдвиги кнопок к центру и вниз, на сколько выше столбик (замер ширин и высот кнопок). `drift` —
 *  на сколько центр коробки уходит влево вместе с колодой: эта часть сдвига идёт кривой колоды (кнопки стоят, пока
 *  коробка сужается), остальное (`x1s`, `x2s`) — своим тактом, после того как вторая ушла вниз: кнопки не наезжают друг на
 *  друга и каждая идёт в одну сторону. */
export function actsColumn(b1: { w: number; h: number }, b2: { w: number; h: number }, gap: number, drift = 0) {
  const x1 = (gap + b2.w) / 2, x2 = -(gap + b1.w) / 2;
  return {
    x1, x2, x1s: x1 - drift, x2s: x2 - drift,
    // ряд выровнен по центру по высоте: центр второй — под первой через зазор
    y2: b1.h / 2 + gap + b2.h / 2,
    grow: b1.h + gap + b2.h - Math.max(b1.h, b2.h),
  };
}

const GAP = 16;
const REASON: CSSProperties = { margin: "8px 0 0", fontSize: 15, fontWeight: 600, lineHeight: "24px", color: "#FFFFFF" };

export function Failed({ text, onBack, onRetry, morph, wide, narrow }: {
  text: string; onBack(): void; onRetry(): void;
  /** Обе раскладки плиты (columns.ts). */
  morph: BuildMorph;
  /** Окно шире 900 px (колода и помощник рядом); уже — одна раскладка, как B-failed. */
  wide: boolean;
  /** Колода сужена помощником: активна узкая копия стопок. */
  narrow: boolean;
}) {
  const t = failText(morph);
  const col = wide && morph.failCol;
  // центр коробки уходит влево вместе с колодой: коробка — левая колонка (широкая → узкая), поля симметричные
  const drift = (morph.list - morph.left) / 2;
  // ширины и высоты кнопок и высоты копий текста — постоянные: по ним сдвиги в столбик и линейная высота стопок
  const box = useRef<HTMLDivElement>(null);
  const acts = useRef<HTMLDivElement>(null);
  const [cv, setCv] = useState<CSSProperties>({});
  useLayoutEffect(() => {
    let alive = true;
    const run = () => {
      if (!alive) return;
      // стопки заголовка и причины: высота в широкой (`--hw`) и на сколько выше в узкой (`--hdd`) — на ходу она идёт
      // линейно, той же кривой, что сдвиг кнопок (build.css): всё вертикальное в коробке движется в одну сторону
      for (const st of box.current?.querySelectorAll<HTMLElement>(".bf-tx") ?? []) {
        const [cw, cn] = [...st.children] as HTMLElement[];
        const w = cw.offsetHeight;
        st.style.setProperty("--hw", `${w}px`);
        st.style.setProperty("--hdd", `${Math.max(w, cn.scrollHeight) - w}px`);
      }
      const [a, b] = [...(acts.current?.children ?? [])] as HTMLElement[];
      if (!col || !a || !b) return;
      const c = actsColumn({ w: a.offsetWidth, h: a.offsetHeight }, { w: b.offsetWidth, h: b.offsetHeight }, GAP, drift);
      const next = { "--bf-a": `${drift}px`, "--bf-x1": `${c.x1s}px`, "--bf-x2": `${c.x2s}px`, "--bf-y2": `${c.y2}px`, "--bf-gr": `${c.grow}px` } as CSSProperties;
      setCv((cur) => (JSON.stringify(cur) === JSON.stringify(next) ? cur : next));
    };
    run();
    void document.fonts?.ready.then(run);
    return () => {
      alive = false;
    };
  }, [col, drift, text, t.title.stack, t.reason.stack, t.title.wide, t.title.narrow, t.reason.wide, t.reason.narrow]);
  // стопка: отступ сверху — у неё, не у копий (высота стопки — высота копий: по ней её линейная высота на ходу)
  const pair = (tx: string, top: number, w: { wide: number; narrow: number; stack: boolean }, one: (p: { cls?: string; style?: CSSProperties; hidden?: boolean }) => ReactNode) =>
    wide && w.stack ? (
      <div className="hp-tx bf-tx" data-tx={tx} style={{ marginTop: top, "--bf-tw": `${w.wide}px`, "--bf-tn": `${w.narrow}px` } as CSSProperties}>
        {one({ cls: "hp-txw", hidden: narrow, style: { margin: 0 } })}
        {one({ cls: "hp-txn", hidden: !narrow, style: { margin: 0 } })}
      </div>
    ) : one({ style: { maxWidth: wide ? w.narrow : 480 } });
  return (
    <div ref={box} className="p2-box p2-pop bf-empty p2-lic-host bd-errbox" role="alert"
      style={{ position: "absolute", left: 0, right: 0, top: 24, bottom: 0, animationDelay: "120ms" }}>
      <span className="p2-lic p2-lic-d p2-lic-err" aria-hidden="true">
        <span className="p2-lic-b" />
        <span className="p2-lic-f"><Icon name="alert" size={22} /></span>
      </span>
      {pair("b-ttl", 24, t.title, (p) => (
        <h2 className={cls("bf-ttl", p.cls)} style={p.style} aria-hidden={p.hidden || undefined}>Не получилось собрать презентацию</h2>
      ))}
      {pair("b-why", 8, wide ? t.reason : { wide: 480, narrow: 480, stack: false }, (p) => (
        <p className={p.cls} style={{ ...REASON, maxWidth: 480, ...p.style }} aria-hidden={p.hidden || undefined}>{text}</p>
      ))}
      <div ref={acts} className={cls("bd-acts", col && "bd-col")} style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: GAP, marginTop: 32, ...cv }}>
        <button type="button" className="p2-cta" onClick={onBack}>
          <Icon name="arrow-left" size={20} />
          <span>Вернуться к тексту</span>
        </button>
        <button type="button" className="bf-obd" onClick={onRetry}>
          <Icon name="refresh" size={18} />
          <span>Собрать ещё раз</span>
        </button>
      </div>
    </div>
  );
}
