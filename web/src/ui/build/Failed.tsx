// «Не получилось» (boards/B-failed, V2 `bdFailed`): раскадровка гаснет, на её месте встаёт коробка ошибки — иконка-слои
// с красным знаком, «Не получилось собрать презентацию», причина простыми словами, «Вернуться к тексту» и «Собрать ещё
// раз» (тот же запрос). Появляется pop 360 мс через 120 мс.
// Помощник сужает колоду: поля коробки 48 → 24 (V2 версии 100). Сайт: пока помощник закрыт, коробка — как B-failed при
// любой ширине окна (заголовок в строку, причина до 480, кнопки в ряд). Заголовок и причина, которые в узкой колоде
// переносятся иначе (окно около 1280), — стопки из двух копий постоянной ширины (широкая гаснет, узкая проявляется на
// месте, columns.ts `failText`; их высота на ходу идёт линейно). Кнопки всегда в ряд; полным подписям в узкой колоде
// места нет — подписи меняют формулировку на месте («К тексту», «Ещё раз»), и кнопка сужается вместе с колодой, одним
// ходом (ширина подписи — замер обеих). Имя кнопки для чтения с экрана — полное.
import { useLayoutEffect, useRef, type CSSProperties, type ReactNode } from "react";
import { bindShort } from "../../lib/typo";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import type { BuildMorph } from "./columns";
import { failText } from "./columns";

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
  const short = wide && morph.failShort;
  // высоты копий текста и ширины подписей кнопок — постоянные: по ним линейная высота стопок и ширина подписи на ходу
  const box = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    let alive = true;
    const run = () => {
      if (!alive || !box.current) return;
      // стопки заголовка и причины: высота в широкой (`--hw`) и на сколько выше в узкой (`--hdd`) — на ходу она идёт
      // линейно, той же кривой, что колода (build.css): всё вертикальное в коробке движется в одну сторону
      for (const st of box.current.querySelectorAll<HTMLElement>(".bf-tx")) {
        const [cw, cn] = [...st.children] as HTMLElement[];
        const w = cw.offsetHeight;
        st.style.setProperty("--hw", `${w}px`);
        st.style.setProperty("--hdd", `${Math.max(w, cn.scrollHeight) - w}px`);
      }
      for (const lb of box.current.querySelectorAll<HTMLElement>(".bf-lb")) {
        const [lw, ln] = [...lb.children] as HTMLElement[];
        lb.style.setProperty("--lw", `${Math.ceil(lw.scrollWidth)}px`);
        lb.style.setProperty("--ln", `${Math.ceil(ln.scrollWidth)}px`);
      }
    };
    run();
    void document.fonts?.ready.then(run);
    return () => {
      alive = false;
    };
  }, [short, text, t.title.stack, t.reason.stack, t.title.wide, t.title.narrow, t.reason.wide, t.reason.narrow]);
  const label = (full: string, brief: string) => (short
    ? <span className="hp-sw bf-lb"><span className="hp-wo">{full}</span><span className="hp-no">{brief}</span></span>
    : <span>{full}</span>);
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
        <h2 className={cls("bf-ttl", p.cls)} style={p.style} aria-hidden={p.hidden || undefined}>{bindShort("Не получилось собрать презентацию")}</h2>
      ))}
      {pair("b-why", 8, wide ? t.reason : { wide: 480, narrow: 480, stack: false }, (p) => (
        <p className={p.cls} style={{ ...REASON, maxWidth: 480, ...p.style }} aria-hidden={p.hidden || undefined}>{text}</p>
      ))}
      <div className={cls("bd-acts", short && "bd-sht")} style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 16, marginTop: 32 }}>
        <button type="button" className="p2-cta" onClick={onBack} aria-label={short ? "Вернуться к тексту" : undefined}>
          <Icon name="arrow-left" size={20} />
          {label("Вернуться к тексту", "К тексту")}
        </button>
        <button type="button" className="bf-obd" onClick={onRetry} aria-label={short ? "Собрать ещё раз" : undefined}>
          <Icon name="refresh" size={18} />
          {label("Собрать ещё раз", "Ещё раз")}
        </button>
      </div>
    </div>
  );
}
