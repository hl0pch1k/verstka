/** Присутствие уходящего/приходящего содержимого: `mounted` — оно в DOM, `shown` — стоит в открытом состоянии
 *  (класс показа включён). Между ними CSS-переход: вход стартует из закрытого состояния, уход доигрывает до конца. */
export interface Presence { mounted: boolean; shown: boolean }

/** Один шаг к цели `open`.
 *  - Открытие: не смонтировано → смонтировать закрытым; смонтировано → показать (usePresence делает этот шаг со
 *    следующего кадра, чтобы переход входа всегда начинался из закрытого состояния).
 *  - Закрытие: показано → снять показ, оставив смонтированным; не показано → размонтировать (usePresence делает этот шаг
 *    по таймеру, когда уход доиграл).
 *  В цели возвращает тот же объект — без лишней перерисовки. */
export function presenceNext(prev: Presence, open: boolean): Presence {
  if (open) {
    if (!prev.mounted) return { mounted: true, shown: false };
    return prev.shown ? prev : { mounted: true, shown: true };
  }
  if (prev.shown) return { mounted: true, shown: false };
  return prev.mounted ? { mounted: false, shown: false } : prev;
}
