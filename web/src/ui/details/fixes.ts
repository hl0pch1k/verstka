// Автоисправления проверки словами (перенесено из версии до «Слоёв»): «Слайд 10 · Подобран другой макет:
// теперь по образцу слайда 22 шаблона · проход 1». Общие для «Качества» («Исправлено автоматически») и «Файлов»
// («Автоисправления»). Отменённая проверкой правка (`rolled_back`) и попытка без перемены не считаются сделанными.

const ACTION_DONE: Record<string, string> = {
  rematch: "Подобран другой макет",
  synth: "Слайд собран заново",
  condense_text: "Сокращён текст",
  drop_element: "Убран лишний элемент",
  move_inside: "Элемент возвращён в кадр",
  recolor: "Поправлен цвет",
  refont: "Заменён шрифт",
  shrink_text: "Уменьшен шрифт",
  xml: "Поправлено оформление",
  rollback: "Неудачная правка отменена",
};

const str = (v: unknown): string | null => (v === null || v === undefined || v === "" ? null : typeof v === "string" ? v : String(v));

/** «rematch → p9» → «теперь по образцу слайда 9 шаблона»; русская строка — как есть; технические — ничего. */
function resultText(result: string | null, templateSlide: (pid: string) => number | null): string | null {
  if (!result) return null;
  const m = result.match(/→\s*(p\d+)/);
  if (m) {
    const n = templateSlide(m[1]);
    return n ? `теперь по образцу слайда ${n} шаблона` : null;
  }
  return /[а-яё]/i.test(result) && !/^slide \d+:/.test(result) ? result : null;
}

/** Номер слайда шаблона по id макета («p9» → 9) — из разбора шаблона листа; разбора нет — null (строка без «по образцу»). */
export function patternSlideOf(manifest: { patterns: { id: string; source_slide: number }[] } | null | undefined): (pid: string) => number | null {
  return (pid) => manifest?.patterns.find((p) => p.id === pid)?.source_slide ?? null;
}

export interface FixRow { slide: number | null; title: string; extra: string | null; n: number; pass: string | null }

export function appliedRows(fixes: Record<string, unknown>[], slideOf: (outlineId: string) => number | null, templateSlide: (pid: string) => number | null): FixRow[] {
  const out: FixRow[] = [];
  const seen = new Map<string, FixRow>();
  for (const raw of fixes) {
    if (raw.rolled_back === true) continue;
    const action = str(raw.action);
    const kind = str(raw.kind);
    const result = str(raw.result);
    // попытка без перемены («skip» — макет не нашёлся, «kept» — оставлена прежняя вёрстка) — не исправление
    if (result === "skip" || result === "kept") continue;
    const legacy = result?.match(/^slide (\d+):/)?.[1];
    const outline = str(raw.outline_id);
    const slide = typeof raw.slide === "number" ? raw.slide : legacy ? Number(legacy) : outline ? slideOf(outline) : null;
    const said = resultText(result, templateSlide);
    // правка на месте описывает себя целиком («Шрифт заменён на Play…»), остальные — сделанным делом
    const own = action === "xml" && said ? said : null;
    const title = own ?? ACTION_DONE[kind ?? ""] ?? ACTION_DONE[action ?? ""] ?? "Поправлено оформление";
    const extra = own ? null : said;
    const key = `${slide ?? ""}|${title}|${extra ?? ""}`;
    const had = seen.get(key);
    if (had) {
      had.n += 1;
      continue;
    }
    const it = raw.iteration;
    const row: FixRow = { slide, title, extra, n: 1, pass: typeof it === "number" ? `проход ${it}` : null };
    seen.set(key, row);
    out.push(row);
  }
  return out;
}
