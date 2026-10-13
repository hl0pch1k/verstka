// Шапка рабочей области (R-aside): «Слайд 3 из 12 · Неопределённый интеграл», справа — «Замечания» со счётчиком и
// переключателем (когда на слайдах есть замечания или режим включён), стрелки и «На весь экран». Счётчик — открытые
// замечания варианта: янтарный, а в режиме «Замечания» при ошибке — красный (R-remarks). Пока агент исправляет слайд,
// переключатель не нажимается. Просмотр на весь экран — задача 10: обработчик приходит сверху.
import { plural } from "../../lib/utils";
import { cls } from "../kit/cls";
import { Icon } from "../kit/Icon";
import { Switch } from "../kit/Switch";

export function WorkHead({ n, total, title, remarks, remarksOn = false, remarksOff = null, onPrev, onNext, onToggleRemarks, onOpenLightbox }: {
  n: number;
  total: number;
  title: string;
  remarks: { count: number; errors: boolean };
  /** Режим «Замечания» включён. */
  remarksOn?: boolean;
  /** Почему переключатель сейчас не нажимается (агент исправляет слайд); null — нажимается. */
  remarksOff?: string | null;
  onPrev(): void;
  onNext(): void;
  onToggleRemarks(): void;
  onOpenLightbox(): void;
}) {
  const word = plural(remarks.count, "замечание", "замечания", "замечаний").slice(String(remarks.count).length + 1);
  return (
    <div className="p2-in" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, height: 40, animationDelay: "200ms" }}>
      <p style={{ minWidth: 0, margin: 0, fontSize: 15, fontWeight: 700, lineHeight: "24px", color: "#0B1220", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {total > 0 ? `Слайд ${n} из ${total}` : "Слайдов нет"}{" "}
        {title && <span style={{ fontWeight: 500, color: "#5A6272" }}>· {title}</span>}
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: 24, flex: "none" }}>
        {(remarks.count > 0 || remarksOn) && (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span id="ra-swl" style={{ fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#0B1220" }}>Замечания</span>
            <span id="ra-swc" className={cls("ra-cnt", remarksOn && remarks.errors ? "rk-cnt-err" : "ra-cnt-warn")}>
              {remarks.count}
              <span className="p2-sr"> {word} на слайдах, {remarks.errors ? "есть ошибка" : "ошибок нет"}</span>
            </span>
            <span style={{ display: "flex", marginLeft: 4 }}>
              <Switch on={remarksOn} onToggle={onToggleRemarks} labelledBy="ra-swl" describedBy="ra-swc" className="ra-sw" disabled={!!remarksOff}
                title={remarksOff ?? undefined} />
            </span>
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button type="button" className="p2-rbl" onClick={onPrev} disabled={n <= 1} aria-label="Предыдущий слайд" title="Предыдущий слайд (←)">
            <Icon name="chevron-left" size={18} />
          </button>
          <button type="button" className="p2-rbl" onClick={onNext} disabled={n >= total} aria-label="Следующий слайд" title="Следующий слайд (→)">
            <Icon name="chevron-right" size={18} />
          </button>
          <button type="button" className="p2-rbl" onClick={onOpenLightbox} disabled={total === 0} aria-haspopup="dialog" aria-label="На весь экран" title="На весь экран"
            style={{ marginLeft: 8 }}>
            <Icon name="maximize" size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
