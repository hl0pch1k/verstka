import { cls } from "./cls";

/** Переключатель `.p2-sw` (C-params, R-aside): дорожка заливается синим, ручка едет на 20 px за 240 мс.
 *  `className` — дополнительный класс досок (например, `ra-sw` для светлой дорожки в колонке результата). */
export function Switch({ on, onToggle, labelledBy, describedBy, disabled, title, className }: {
  on: boolean;
  onToggle(): void;
  labelledBy?: string;
  describedBy?: string;
  disabled?: boolean;
  title?: string;
  className?: string;
}) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-labelledby={labelledBy} aria-describedby={describedBy}
      className={cls("p2-sw", className, on && "p2-sw-on")} onClick={onToggle} disabled={disabled} title={title}>
      <span className="p2-sw-fill" />
      <span className="p2-sw-knob" />
    </button>
  );
}
