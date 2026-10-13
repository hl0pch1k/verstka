// «Исправить отмеченные» / «Исправить всё автоматически» и «Вернуть как было» на вкладке «Качество». Сама работа и её
// состояние — в хранилище (`fixIssues`, `revertVariant`, `work` по ключу варианта; ui/details/useVariantWork): лист
// закрыли во время исправления — оно идёт дальше, открыли снова — отмеченные приглушены и кнопки выключены, а итог
// «Исправлено N» с «Вернуть как было» держится, пока вариант не изменится снова. Кнопки выключены и тогда, когда над
// вариантом идёт чужая задача (исправление слайда, изображение, возврат из «Агента»).
import { useApp } from "../../store";
import { useStale, type Refresh } from "../shell/StaleLine";
import { undoOffOf } from "../result/slideJob";
import type { Variant } from "../../types";
import { variantRev } from "../../lib/rev";
import { fixView, workKey, type FixView } from "./variantWork";

export interface QualityFix extends FixView {
  /** Исправление или его возврат сохранены, а презентация на экране не перечиталась: строка с «Обновить». */
  refresh: Refresh | null;
  /** Почему «Вернуть как было» не нажимается: презентация несвежая; null — нажимается. */
  undoOff: string | null;
  /** `ids` — что исправить («all» — всё автоматически), `count` — какие замечания считать исправленными. */
  start(ids: string[] | "all", count: string[]): void;
  /** «Вернуть как было» итога исправления. */
  revert(): void;
}

export function useQualityFix(gid: string, v: Variant): QualityFix {
  const { work, busyVariants, fixIssues, revertVariant } = useApp();
  const key = workKey(gid, v.strategy);
  const refresh = useStale(gid);
  const view = fixView(work, key, variantRev(v), busyVariants.includes(key), !!refresh);
  return {
    ...view,
    refresh: view.stale ? refresh : null,
    undoOff: undoOffOf(!!refresh),
    start: (ids, count) => fixIssues(gid, v.strategy, ids, count),
    revert: () => void revertVariant(gid, v.strategy, { by: "quality" }),
  };
}
