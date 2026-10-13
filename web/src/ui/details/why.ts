// Вкладка «Почему так» без React (boards/D-why, V2 модуль details `dlW`): почему у слайда такая форма (довод
// дизайнера, вывод и сноска, другие формы и какие варианты их показывают, критик и правка), как слайд собран из
// шаблона (образец, сходство, доводы подбора, другие подходящие макеты) и строка проверки слайда. Данные — `design[n]`,
// план раскладки `plan.slides`, `agent.critic`, отчёт проверки и разбор шаблона презентации.
import { eventParts } from "../../lib/agent";
import { humanReasons, type Reason } from "../../lib/reasons";
import { kindLabel, plural } from "../../lib/utils";
import type { Generation, LayoutSlide, Pattern, TemplateManifest, Variant } from "../../types";
import { scoreOf, slideHeadline, slideSrc, slidesOf, whyText } from "../result/resultView";
import { altWords } from "./altWords";
import { isMinorIssue, qTone, type QTone } from "./quality";

export interface WhyForm { name: string; text: string; variant: { key: string; name: string; score: number | null } | null; onScreen: string | null }
export interface WhyCrit { who: "Критик" | "Правка"; text: string; arrow: boolean }
export interface WhyAlt { key: string; src: string | null; cap: string; sim: string; label: string }

export interface WhyView {
  n: number;
  total: number;
  cap: string;
  title: string;
  src: string | null;
  why: string | null;
  /** Довода у слайда нет — объяснение просится у сервера (`api.explain`). */
  ask: boolean;
  dl: { t: string; d: string }[];
  forms: WhyForm[];
  crit: WhyCrit[];
  sample: { src: string | null; caption: string; label: string } | null;
  /** Слайд собран заново по сетке шаблона (не по образцу). */
  composed: boolean;
  own: { src: string | null; alt: string };
  ownCaption: string;
  sim: { pct: number; note: string } | null;
  reasons: Reason[];
  alts: WhyAlt[];
  check: { text: string; tone: QTone | null } | null;
}

/** Запись раскладки слайда `n` (по id плана, иначе по месту). */
export function planEntry(v: Variant, n: number): LayoutSlide | null {
  const id = v.outline?.slides[n - 1]?.id;
  return (id ? v.plan?.slides.find((s) => s.outline_id === id) : null) ?? null;
}

const pct = (score: number) => Math.round(Math.min(1, Math.max(0, score)) * 100);

export function whyView(g: Generation, v: Variant, n: number, manifest: TemplateManifest | null, titleOf: (name: string) => string): WhyView {
  const total = slidesOf(v);
  const o = v.outline?.slides[n - 1] ?? null;
  const d = v.design?.find((x) => x.index === n) ?? null;
  const headline = slideHeadline(v, n);
  const spec = d?.spec_ref ?? o?.spec_ref ?? null;
  const why = whyText(v, n);

  const takeaway = (d?.takeaway ?? o?.takeaway ?? "").trim();
  const footnote = (d?.footnote ?? o?.footnote ?? "").trim();
  const dl = [takeaway && { t: "Вывод", d: takeaway }, footnote && { t: "Сноска", d: footnote }].filter((x): x is { t: string; d: string } => !!x);

  // другие формы: вариант, который показывает слайд в этой форме, — кнопкой; текущий — меткой «на экране»
  const alts = d?.alternatives ?? (o?.alternatives ?? []).map((a) => ({ kind: a.kind || null, label: null, text: a.change || null, used_in: [] as string[] }));
  const order = g.variants.map((x) => x.strategy);
  const forms: WhyForm[] = alts.map((a) => {
    const used = (a.used_in ?? []).filter((s) => order.includes(s));
    const other = order.find((s) => s !== v.strategy && used.includes(s)) ?? null;
    const target = other ? g.variants.find((x) => x.strategy === other) ?? null : null;
    const sc = target ? scoreOf(g, target) : null;
    return {
      ...altWords(a),
      onScreen: used.includes(v.strategy) ? `${titleOf(v.strategy)} · на экране` : null,
      variant: !used.includes(v.strategy) && other ? { key: other, name: titleOf(other), score: sc === null ? null : Math.round(sc) } : null,
    };
  });

  const crit: WhyCrit[] = [];
  for (const e of (v.agent?.critic ?? []).filter((x) => x.slide === n)) {
    const { text, fix } = eventParts(e);
    if (e.step === "revise") crit.push({ who: "Правка", text, arrow: false });
    else {
      crit.push({ who: "Критик", text, arrow: false });
      if (fix) crit.push({ who: "Правка", text: fix, arrow: true });
    }
  }

  // как собран слайд: образец шаблона (у собранного заново — ближайший, только того же типа) и сходство
  const ok = !!manifest && manifest.template_id === g.template_id;
  const byId = (id: string | null | undefined): Pattern | null => (ok && id ? manifest.patterns.find((p) => p.id === id) ?? null : null);
  const entry = planEntry(v, n);
  const composed = entry?.mode === "synth";
  const pattern = entry?.mode === "clone" ? byId(entry.pattern_id) : null;
  const near = composed ? byId(entry?.alternatives[0]?.[0]) : null;
  const nearest = near && o && near.kind === o.kind && o.kind !== "chart" ? near : null;
  const sp = pattern ?? nearest;
  const sample = sp ? {
    src: sp.thumbnail_url ?? null,
    caption: pattern ? `Образец: слайд ${sp.source_slide} шаблона` : `Ближайший образец: слайд ${sp.source_slide} шаблона`,
    label: `Слайд ${sp.source_slide} шаблона: ${kindLabel(sp.kind)}`,
  } : null;

  let sim: WhyView["sim"] = null;
  if (entry && !composed) {
    const match = pct(entry.score);
    const others = entry.alternatives.filter(([pid]) => pid !== entry.pattern_id).map(([, s]) => s);
    const runnerUp = others.length ? pct(Math.max(...others)) : null;
    const note = !pattern ? "Ни один образец не подошёл достаточно хорошо — слайд собран с нуля в стиле шаблона"
      : runnerUp === null ? "Единственный макет шаблона, подходящий для такого слайда"
        : runnerUp <= match ? `Лучший из рассмотренных: у остальных сходство ${runnerUp}% и ниже`
          : entry.reasons.some((r) => r.startsWith("автофикс:")) ? `Заменён проверкой качества: макет со сходством ${runnerUp}% дал замечания`
            : "Выбран с учётом стиля варианта и соседних слайдов";
    sim = { pct: match, note };
  }
  const reasons = entry ? humanReasons(entry.reasons, titleOf, (pid) => byId(pid)?.source_slide ?? null) : [];
  const altList: WhyAlt[] = composed || !entry ? [] : entry.alternatives
    .map(([pid, score]) => ({ p: byId(pid), score }))
    .filter((a): a is { p: Pattern; score: number } => !!a.p && a.score > 0.05 && a.p.id !== pattern?.id)
    .slice(0, 3)
    .map(({ p, score }) => ({
      key: p.id, src: p.thumbnail_url ?? null, cap: `Слайд ${p.source_slide} · ${kindLabel(p.kind)}`, sim: `сходство ${pct(score)}%`,
      label: `Слайд ${p.source_slide} шаблона: ${kindLabel(p.kind)}`,
    }));

  // проверка слайда: его замечания (без мелких заметок) и тон худшего
  let check: WhyView["check"] = null;
  if (v.audit) {
    const own = v.audit.issues.filter((i) => i.slide === n && !isMinorIssue(i));
    const tones = own.map(qTone);
    const tone = tones.includes("err") ? "err" : tones.includes("warn") ? "warn" : tones.length ? "model" : null;
    check = { text: own.length ? plural(own.length, "замечание", "замечания", "замечаний") : "замечаний нет", tone };
  }

  return {
    n, total, cap: `Слайд ${n} / ${total} · ${kindLabel(d?.kind ?? o?.kind)}`, title: headline || "Без заголовка",
    src: spec ? `В вашем тексте — слайд ${spec}` : null, why, ask: !why, dl, forms, crit,
    sample, composed, own: { src: slideSrc(v, n), alt: headline ? `Ваш слайд ${n}: ${headline}` : `Ваш слайд ${n}` },
    ownCaption: !sample && composed ? "Собран заново по сетке, шрифтам и цветам шаблона" : "Ваш слайд",
    sim, reasons, alts: altList, check,
  };
}

/** Довод из объяснения сервера (`api.explain`: «Слайд N — …», «Почему так: …», «Вёрстка: …»): строка «Почему так»,
 *  а её нет — всё, кроме первой строки (заголовок слайда). */
export function explainWhy(text: string | null | undefined): string | null {
  const lines = (text ?? "").split("\n").map((l) => l.trim()).filter(Boolean);
  const why = lines.find((l) => /^Почему так:/i.test(l));
  if (why) return why.replace(/^Почему так:\s*/i, "") || null;
  return lines.slice(1).join(" ") || null;
}
