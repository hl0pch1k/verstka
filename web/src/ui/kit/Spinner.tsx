import { cls } from "./cls";
import { strokeFor } from "./Icon";

/** Дуга загрузки (G-history; S-motion «1000 мс по кругу · линейно · transform (rotate)»): три четверти окружности
 *  крутятся равномерно, класс `gh-spin`. Цвет — currentColor. */
export function Spinner({ size = 20, className, label }: { size?: number; className?: string; label?: string }) {
  return (
    <svg className={cls("gh-spin", className)} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={strokeFor(size)} strokeLinecap="round" aria-hidden={label ? undefined : true} role={label ? "img" : undefined}
      aria-label={label}>
      <path d="M12 3a9 9 0 1 1-9 9" />
    </svg>
  );
}
