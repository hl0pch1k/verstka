// Слой «Слайд N шаблона» без React (boards/D-pattern, V2 модуль details `dlX`; логика мест — как до
// «Слоёв»): образец шаблона с рамками мест для содержания, качество образца, как определён его тип
// (голоса правил и моделей), декор и места по порядку сверху вниз — свои места образца, группы карточек диапазоном
// номеров, область данных. Иконки образца — одной строкой без номера.
import { kindLabel, plural } from "../../lib/utils";
import type { BboxFrac, Pattern, RepeatGroup, Slot, TemplateManifest } from "../../types";

/** Цвета легенды доски: заголовок, текст, изображение, данные. */
export const PLACE_COLOR = { title: "#2563EB", text: "#5A6272", image: "#B45309", data: "#DC2626" } as const;

const ROLE_RU: Record<string, string> = {
  title: "заголовок", subtitle: "подзаголовок", body: "текст", bullet_list: "список", paragraph: "абзац",
  card_title: "заголовок", card_body: "текст", card_text: "текст", card_number: "число", number: "число", number_label: "подпись числа", label: "подпись",
  caption: "подпись", image: "изображение", picture: "изображение", chart: "диаграмма", table: "таблица", quote: "цитата",
  author: "автор", section: "раздел", agenda_item: "пункт повестки", step: "шаг", date: "дата", logo: "логотип", icon: "иконка",
  footer: "колонтитул", page_number: "номер слайда", code: "код", name: "имя", position: "должность",
};
const roleRu = (role: string) => ROLE_RU[role] ?? role.replace(/_/g, " ");
const colorOf = (role: string) => (role === "title" || role === "section" ? PLACE_COLOR.title
  : /image|picture|logo|icon/.test(role) ? PLACE_COLOR.image : /chart|table|number|code/.test(role) ? PLACE_COLOR.data : PLACE_COLOR.text);

export interface Place { id: string; num: string; role: string; extra: string; c: string; sample: string; note: string | null }
export interface Frame { key: string; id: string; n: string; x: string; y: string; w: string; h: string; c: string; dash: boolean }
export interface PatternView {
  n: number; title: string; desc: string; img: string | null; fallback: string | null; alt: string; q: number;
  votes: { src: string; kind: string; p: string; agree: boolean }[]; agree: string; decor: string;
  placesH: string; places: Place[]; frames: Frame[]; prev: number | null; next: number | null; pos: string;
}

const pc = (v: number) => `${+(v * 100).toFixed(2)}%`;
const quote = (t: string | null) => (t?.trim() ? `«${t.trim().split("\n")[0]}»` : "");

/** Чем повторяется группа: карточки, шаги, числа, люди — по типу образца. */
function itemWord(kind: string, n: number): string {
  if (kind === "process" || kind === "timeline" || kind === "agenda") return plural(n, "шаг", "шага", "шагов");
  if (kind === "stat_row" || kind === "big_number") return plural(n, "число", "числа", "чисел");
  if (kind === "team") return plural(n, "человек", "человека", "человек");
  return plural(n, "карточка", "карточки", "карточек");
}

/** «2 ячейки · колонка · до 4». */
function groupSummary(g: RepeatGroup): string {
  const cells = g.member_shape_ids.length;
  if (g.fixed) return `${plural(cells, "ячейка", "ячейки", "ячеек")} · ровно ${cells}`;
  const axis = g.axis === "row" ? "ряд" : g.axis === "column" ? "колонка" : g.axis === "grid" ? `сетка ${g.rows}×${g.cols}` : g.axis;
  const range = g.min_n > 1 && g.min_n < g.max_n ? `от ${g.min_n} до ${g.max_n}` : `до ${g.max_n}`;
  return `${plural(cells, "ячейка", "ячейки", "ячеек")} · ${axis} · ${range}`;
}

export function patternView(m: TemplateManifest, n: number): PatternView | null {
  const list = m.patterns.slice().sort((a, b) => a.source_slide - b.source_slide);
  const at = list.findIndex((p) => p.source_slide === n);
  if (at < 0) return null;
  const p: Pattern = list[at];
  const grouped = new Set(p.repeat_groups.flatMap((g) => g.member_shape_ids.flat()));
  const own = p.slots.filter((s) => !grouped.has(s.shape_id));
  const icons = own.filter((s) => s.role === "icon");

  type Item = { y: number; x: number; kind: "slot"; s: Slot } | { y: number; x: number; kind: "group"; g: RepeatGroup; boxes: BboxFrac[] } | { y: number; x: number; kind: "data"; b: BboxFrac };
  const items: Item[] = [
    ...own.filter((s) => s.role !== "icon").map((s) => ({ y: s.bbox.y, x: s.bbox.x, kind: "slot" as const, s })),
    ...p.repeat_groups.map((g) => {
      const slots = p.slots.filter((s) => g.member_shape_ids.flat().includes(s.shape_id));
      const boxes = g.cell_boxes?.length ? g.cell_boxes : [];
      const top = boxes[0] ?? slots.reduce<BboxFrac | null>((a, s) => (!a || s.bbox.y < a.y ? s.bbox : a), null) ?? { x: 0, y: 1, w: 0, h: 0 };
      return { y: top.y, x: top.x, kind: "group" as const, g, boxes };
    }),
    ...(p.data_box ? [{ y: p.data_box.y, x: p.data_box.x, kind: "data" as const, b: p.data_box }] : []),
  ].sort((a, b) => a.y - b.y || a.x - b.x);

  const places: Place[] = [];
  const frames: Frame[] = [];
  let k = 0;
  const frame = (key: string, id: string, num: number, b: BboxFrac, c: string, dash: boolean) =>
    frames.push({ key, id, n: String(num), x: pc(b.x), y: pc(b.y), w: pc(b.w), h: pc(b.h), c, dash });
  for (const it of items) {
    if (it.kind === "slot") {
      const note = p.note_slot === it.s.id;
      const c = colorOf(it.s.role);
      k += 1;
      places.push({ id: it.s.id, num: String(k), role: note ? "поле примечания" : roleRu(it.s.role), extra: "", c, sample: quote(it.s.sample_text), note: note ? "сюда встанет вывод слайда" : null });
      frame(it.s.id, it.s.id, k, it.s.bbox, c, false);
    } else if (it.kind === "group") {
      const cells = it.g.member_shape_ids.length;
      const first = new Set(it.g.member_shape_ids[0] ?? []);
      const roles = [...new Set(p.slots.filter((s) => first.has(s.shape_id)).map((s) => roleRu(s.role)))].join(" + ");
      const from = k + 1;
      k += cells;
      places.push({ id: it.g.id, num: cells > 1 ? `${from}–${k}` : String(from), role: itemWord(p.kind, cells), extra: roles ? `· ${roles}` : "", c: PLACE_COLOR.text, sample: groupSummary(it.g), note: null });
      it.boxes.forEach((b, j) => frame(`${it.g.id}-${j}`, it.g.id, from + j, b, PLACE_COLOR.text, true));
    } else {
      k += 1;
      const rows = p.data_rows ? `· ${plural(p.data_rows, "строка", "строки", "строк")}` : "";
      places.push({ id: "data", num: String(k), role: p.data_kind === "chart" ? "диаграмма" : "таблица", extra: rows, c: PLACE_COLOR.data, sample: "", note: null });
      frame("data", "data", k, it.b, PLACE_COLOR.data, false);
    }
  }
  if (icons.length) places.push({ id: "icons", num: "", role: plural(icons.length, "иконка", "иконки", "иконок"), extra: "", c: PLACE_COLOR.image, sample: "", note: null });

  const c = p.classification;
  const votes = c ? ([["правила", c.heuristic], ["языковая модель", c.llm], ["модель зрения", c.vlm]] as const)
    .filter(([, v]) => !!v)
    .map(([src, v]) => ({ src, kind: kindLabel(v!.kind), p: `${Math.round(v!.confidence * 100)} %`, agree: v!.kind === c.kind })) : [];
  const decor = p.decor_assets.length;
  const kind = kindLabel(p.kind);
  return {
    n, title: `Слайд ${n} шаблона · ${kind}`, desc: p.family === "dark" ? "Тёмный фон" : "Светлый фон",
    img: p.thumbnail_url ? p.thumbnail_url.replace("/thumbs/", "/slides/") : null, fallback: p.thumbnail_url ?? null,
    alt: `Образец: слайд ${n} шаблона — ${kind}`, q: Math.round(Math.min(1, Math.max(0, p.quality)) * 100),
    votes, agree: `согласие ${votes.filter((v) => v.agree).length} из ${votes.length}`,
    decor: decor ? `${plural(decor, "декоративный элемент", "декоративных элемента", "декоративных элементов")} ${decor === 1 ? "сохраняется" : "сохраняются"} как в образце` : "Декоративных элементов нет",
    placesH: `${plural(k, "место", "места", "мест")} для содержания`, places, frames,
    prev: list[at - 1]?.source_slide ?? null, next: list[at + 1]?.source_slide ?? null, pos: `${n} / ${m.n_slides}`,
  };
}
