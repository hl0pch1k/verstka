// Строка «Изменения сохранены, но презентация на экране не обновилась: …» у места действия (исправление слайда,
// изображение, «Исправить всё», «Вернуть как было»): красная строка с причиной и «Обновить» — презентация читается ещё
// раз (store `refreshDeck`), пока читается — дуга в кнопке, строка стоит. Перечиталась — хранилище больше не держит её
// несвежей, и место действия показывает итог вместо строки; не перечиталась — новая причина сменяет прежнюю
// перекрёстным затуханием (useSwap).
import type { CSSProperties } from "react";
import { useApp } from "../../store";
import { reloadFailText } from "../helper/chat";
import { Arc } from "../kit/Arc";
import { ErrorLine } from "../kit/ErrorLine";
import { Icon } from "../kit/Icon";
import { useSwap } from "../kit/useSwap";

export interface Refresh { text: string; busy: boolean; onRefresh(): void }

export { STALE_FIRST } from "../result/slideJob";

/** Несвежая ли презентация `gid` (store `stale`): строка и «Обновить»; null — свежая. */
export function useStale(gid: string): Refresh | null {
  const { stale, refreshing, refreshDeck } = useApp();
  if (!stale || stale.gid !== gid) return null;
  const busy = refreshing === gid;
  return { text: reloadFailText(stale.error), busy, onRefresh: () => void (busy || refreshDeck(gid)) };
}

export function StaleLine({ r, lines = 3, style }: { r: Refresh; lines?: number; style?: CSSProperties }) {
  const t = useSwap(r.text);
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 8, minWidth: 0, ...style }}>
      <span className={t.cls} style={{ display: "flex", flex: 1, minWidth: 0 }}>
        <ErrorLine text={t.shown} lines={lines} />
      </span>
      <button type="button" className="p2-gb" onClick={r.onRefresh} aria-busy={r.busy || undefined}
        title={r.busy ? "Перечитываю презентацию…" : "Перечитать презентацию"}
        style={{ flex: "none", height: 32, margin: "-6px -12px -6px 0", padding: "0 12px", fontSize: 14, lineHeight: "20px", cursor: r.busy ? "progress" : undefined }}>
        {r.busy ? <Arc size={16} /> : <Icon name="refresh" size={16} />}
        <span>Обновить</span>
      </button>
    </div>
  );
}
