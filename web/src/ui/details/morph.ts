// Обновление на месте (V2 v105 `dwRebuild`: слайд пересобран, а вкладка «Почему так» остаётся той же): меняется только
// то, что изменилось, — каждая такая часть гаснет (120 мс), подменяется невидимой, то, что под ней сдвинулось,
// доезжает transform'ом (240 мс, useMorph), и она проявляется (240 мс). Остальное не мигает. Части — по именам
// (`id` → подпись содержимого `sig`); здесь — шаги без React и DOM: что показано и что гаснет.

export type MorphPhase = "out" | "move" | "in" | null;
/** Подписи частей: `id` → строка, по которой видно, что часть изменилась. */
export type Sigs = Record<string, string>;

export interface MorphState<V> {
  /** Ход: out — изменившиеся части гаснут (на виду прежнее), move — подменены невидимыми, остальное доезжает, in —
   *  проявляются. null — покой: на виду то, что есть сейчас. */
  phase: MorphPhase;
  /** Что на виду во время хода (до подмены — прежнее, после — то, что было на момент подмены). */
  held: V | null;
  heldSigs: Sigs;
  /** Части, которые меняются в этом ходе. */
  changed: string[];
}

export const morph0 = <V>(): MorphState<V> => ({ phase: null, held: null, heldSigs: {}, changed: [] });

/** Части, подписи которых различаются (и появившиеся, и пропавшие). */
export function diffSigs(a: Sigs, b: Sigs): string[] {
  const out: string[] = [];
  for (const id of Object.keys(a)) if (a[id] !== b[id]) out.push(id);
  for (const id of Object.keys(b)) if (!(id in a)) out.push(id);
  return out;
}

/** Ключ подписей: одинаковые подписи — одинаковый ключ. */
export const sigsKey = (s: Sigs): string => Object.keys(s).sort().map((k) => `${k}\u0001${s[k]}`).join("\u0002");

export type MorphAction<V> =
  /** Ход начался: на виду — прежнее (`held`), гаснет `changed`. */
  | { type: "start"; held: V; heldSigs: Sigs; changed: string[] }
  /** Пока гаснет, изменилось ещё: гаснет и это. */
  | { type: "more"; changed: string[] }
  /** Погасло: на виду — новое (`view`), изменившиеся части невидимы. */
  | { type: "swap"; view: V; sigs: Sigs }
  /** Доехало: проявляются. */
  | { type: "in" }
  /** Проявилось: покой. */
  | { type: "end" };

export function morphNext<V>(s: MorphState<V>, a: MorphAction<V>): MorphState<V> {
  switch (a.type) {
    case "start":
      return s.phase ? s : { phase: "out", held: a.held, heldSigs: a.heldSigs, changed: a.changed };
    case "more": {
      if (s.phase !== "out") return s;
      const add = a.changed.filter((id) => !s.changed.includes(id));
      return add.length ? { ...s, changed: [...s.changed, ...add] } : s;
    }
    case "swap": {
      if (s.phase !== "out") return s;
      const changed = [...s.changed];
      for (const id of diffSigs(s.heldSigs, a.sigs)) if (!changed.includes(id)) changed.push(id);
      return { phase: "move", held: a.view, heldSigs: a.sigs, changed };
    }
    case "in":
      return s.phase === "move" ? { ...s, phase: "in" } : s;
    case "end":
      return s.phase === "in" ? morph0<V>() : s;
  }
}

/** Класс части `id` на этом шаге: гаснет, невидима (без перехода) или проявляется; не меняется — без класса. */
export function morphCls(s: Pick<MorphState<unknown>, "phase" | "changed">, id: string): string | undefined {
  if (!s.phase || !s.changed.includes(id)) return undefined;
  return s.phase === "out" ? "fx-out" : s.phase === "move" ? "fx-hold" : "fx-in";
}

/** Сдвиг одного элемента при подмене: где был и где стал (относительно общей обёртки). */
export interface Moved { dx: number; dy: number }

/** Сдвиг относительно ближайшего сдвигаемого предка: предок уже везёт элемент своим transform'ом. Меньше полпикселя —
 *  не сдвиг. */
export function relMove(own: Moved, parent: Moved | null): Moved | null {
  const dx = own.dx - (parent?.dx ?? 0);
  const dy = own.dy - (parent?.dy ?? 0);
  return Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5 ? null : { dx, dy };
}
