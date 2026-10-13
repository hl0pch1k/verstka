// Разметка сцены в режиме «Замечания» (R-remarks, R-fixed; V2 `rm-mk`): рамки мест замечаний (`rk-frame`, 2 px цвета
// важности), номера у их углов (`rk-pin`, цифры в кружках) и галочки исправленных (`rd-okpin`). Выбранная рамка
// затемняет остальной слайд; «весь слайд» обводится по краю, только выбранным. Слой проявляется 240 мс после
// включения режима и гаснет вместе с ним (`rm-out`); на другом слайде его содержимое проявляется заново, номера
// всплывают по 40 мс. Геометрия — marks.ts `stageMarks`.
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import type { Frame, OkPin, Pin } from "./marks";

export function StageMarks({ k, frames, pins, oks, out, delay, onPick }: {
  /** Ключ содержимого: слайд и вид панели — новое содержимое проявляется заново. */
  k: string;
  frames: Frame[];
  pins: Pin[];
  oks: OkPin[];
  /** Режим выключается или сцена — эскиз исправления: слой гаснет, номера не нажимаются. */
  out: boolean;
  /** Режим только что включён: номера ждут, пока проявится панель (V2 `rmD`: +200 мс). */
  delay: number;
  onPick(id: string): void;
}) {
  return (
    <span className={cls("rm-mk", out && "rm-out")}>
      <span key={k} className="rm-in">
        {frames.map((f) => (
          <span key={f.key} className={cls("rk-frame", `rk-frame-${f.tone}`, f.dim && "rk-frame-on", f.on && !f.dim && "rk-frame-lift")} aria-hidden="true"
            style={{ left: f.left, top: f.top, width: f.width, height: f.height }} />
        ))}
        {pins.map((p, i) => (
          <button key={p.id} type="button" className={cls("rk-pin p2-pop", `rk-${p.tone}`)} aria-pressed={p.on} aria-label={p.label} title={p.label}
            onClick={() => onPick(p.id)} style={{ left: p.left, top: p.top, animationDelay: `${delay + 80 + Math.min(i, 6) * 40}ms` }}>
            {p.n}
          </button>
        ))}
        {oks.map((o, i) => (
          <span key={o.id} className="rd-okpin p2-pop" role="img" aria-label={o.label} title={o.label}
            style={{ left: o.left, top: o.top, animationDelay: `${delay + 120 + Math.min(i, 6) * 40}ms` }}>
            <Icon name="check" size={12} />
          </span>
        ))}
      </span>
    </span>
  );
}
