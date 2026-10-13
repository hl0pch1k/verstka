// Слои сцены результата без React. Каждое превью — свой слой (свой <img>, ключ — id): новое ложится сверху невидимым и
// ждёт, пока его картинка загрузится и декодируется (`ready`), затем проявляется (ra-xf 240 мс) и, проявившись (`done`),
// снимает слои под собой. Слой не пересоздаётся, пока лежит в стопке, поэтому проявляющееся превью, которое накрыло
// следующее, доигрывает своё затухание, а не вспыхивает; сцена никогда не остаётся пустой серой рамкой.

export interface Shot {
  id: number;
  src: string;
  alt: string;
  /** Картинка загружена и декодирована: слой видим (проявляется или уже проявился). */
  ready: boolean;
  /** Слой проявился целиком: под ним ничего не видно. */
  done: boolean;
}

const withAlt = (ls: Shot[], alt: string): Shot[] => {
  const top = ls[ls.length - 1];
  return !top || top.alt === alt ? ls : [...ls.slice(0, -1), { ...top, alt }];
};

/** Сцене дали превью `src`. Тот же src сверху — меняется только подпись. Иначе невидимые (ещё не готовые) слои уходят —
 *  их никто не видел, — и сверху ложится новый, ждущий своей картинки. Слайдов нет (`src` null) — сцена пустая. */
export function pushShot(ls: Shot[], src: string | null, alt: string, id: number = 0): Shot[] {
  if (!src) return ls.length ? [] : ls;
  if (ls[ls.length - 1]?.src === src) return withAlt(ls, alt);
  const seen = ls.filter((l) => l.ready);
  if (seen[seen.length - 1]?.src === src) return withAlt(seen, alt);
  return [...seen, { id, src, alt, ready: false, done: false }];
}

/** Картинка слоя `id` готова. `instant` — готова сразу (декодирована заранее): если под слоем нечего сменять (сцена
 *  пуста), он встаёт без затухания — сцена входит вместе с плитой. `still` — движение выключено («уменьшить
 *  движение»): слой сразу проявлен, слои под ним снимаются. */
export function shotReady(ls: Shot[], id: number, instant: boolean, still: boolean = false): Shot[] {
  const k = ls.findIndex((l) => l.id === id);
  if (k < 0) return ls;
  const under = ls.slice(0, k).some((l) => l.ready);
  if (still || (instant && !under)) return [{ ...ls[k], ready: true, done: true }, ...ls.slice(k + 1)];
  return ls.map((l, i) => (i === k ? { ...l, ready: true } : l));
}

/** Слой `id` проявился целиком: слои под ним больше не видны и снимаются. */
export function shotDone(ls: Shot[], id: number): Shot[] {
  const k = ls.findIndex((l) => l.id === id);
  if (k < 0) return ls;
  return [{ ...ls[k], done: true }, ...ls.slice(k + 1)];
}
