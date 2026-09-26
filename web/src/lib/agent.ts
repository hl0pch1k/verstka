// The planning agent's work (Agent v2) as a timeline of plain steps: Аналитик → Архитектор (when the text did not
// describe the slides) → Дизайнер (a line per slide with its form) → Критик → Правка → Вёрстка → Проверка.
// The agent's own steps come as events {step, message, slide, variant, fix}; «Вёрстка» and «Проверка» follow the
// pipeline's plain progress messages («visual: rendered slide 3/10», «export: …»). Pure functions, no React.
import type { AgentEvent, DeckOutline, JobEvent, Variant } from "../types";
import { plainTerms } from "./plain";
import { plural } from "./utils";

export type PhaseKey = "analyst" | "architect" | "designer" | "critic" | "revise" | "layout" | "check";
export type PhaseStatus = "done" | "active" | "pending" | "skipped";

export interface PhaseDef { key: PhaseKey; title: string; hint: string; optional?: boolean }

export const PHASES: PhaseDef[] = [
  { key: "analyst", title: "Аналитик", hint: "читает текст: какие слайды, цифры и диаграммы нужны" },
  { key: "architect", title: "Архитектор", hint: "выстраивает сюжет: разделы и слайды", optional: true },
  { key: "designer", title: "Дизайнер", hint: "придумывает форму каждого слайда" },
  { key: "critic", title: "Критик", hint: "сверяет план с текстом и правилами" },
  { key: "revise", title: "Правка", hint: "переделывает слайды с замечаниями" },
  { key: "layout", title: "Вёрстка", hint: "раскладывает слайды по макетам шаблона" },
  { key: "check", title: "Проверка", hint: "шрифты, цвета, отступы — и исправления" },
];

const ORDER: Record<PhaseKey, number> = Object.fromEntries(PHASES.map((p, i) => [p.key, i])) as Record<PhaseKey, number>;
export const phaseOrder = (k: PhaseKey) => ORDER[k];
export const laterPhase = (a: PhaseKey | null | undefined, b: PhaseKey | null | undefined): PhaseKey | null =>
  !a ? b ?? null : !b ? a : ORDER[b] > ORDER[a] ? b : a;

/** The agent's step (contract names) → the phase of the timeline; null for a step this UI does not know. */
export function phaseOfStep(step: string | null | undefined): PhaseKey | null {
  switch ((step ?? "").toLowerCase()) {
    case "analyst": return "analyst";
    case "architect": return "architect";
    case "designer": return "designer";
    case "critic": return "critic";
    case "revise": return "revise";
    case "compile": return "layout";
    default: return null;
  }
}

/** Where a plain progress message of the pipeline is («analyze: …», «plan: 3 variants», «visual: rendered slide 3/10»). */
export function phaseOfMessage(message: string): PhaseKey | null {
  const m = message.trim();
  if (/^(analyze|plan): /.test(m)) return "analyst";
  if (/^export: /.test(m)) return "check";
  const r = m.match(/^([a-z_]+): (.+)$/);
  if (!r) return null;
  const what = r[2];
  if (/^planned \d+ slides/.test(what) || /^rendered slide/.test(what)) return "layout";
  if (what === "audit" || /^autofix/.test(what) || /^done in /.test(what)) return "check";
  return null;
}

export function phaseOfEvent(ev: JobEvent): PhaseKey | null {
  return ev.type === "agent" ? phaseOfStep(ev.step) : ev.message ? phaseOfMessage(ev.message) : null;
}

export function toAgentEvent(ev: JobEvent): AgentEvent {
  return { step: ev.step ?? "", message: ev.message, slide: ev.slide ?? null, variant: ev.variant ?? null, t: ev.t, seq: ev.seq, fix: ev.fix ?? null };
}

const sameEvent = (a: AgentEvent, b: AgentEvent) =>
  a.seq !== undefined && b.seq !== undefined ? a.seq === b.seq : a.step === b.step && a.message === b.message && a.slide === b.slide && a.variant === b.variant;

/** Appends an event unless the list has it (the stream and the polled job record both deliver it). */
export function addAgentEvent(list: AgentEvent[] | undefined, ev: AgentEvent): AgentEvent[] {
  const cur = list ?? [];
  return cur.some((x) => sameEvent(x, ev)) ? cur : [...cur, ev];
}

/** An event of the timeline: its phase and, when the line holds for some variants but not all, their names. */
export type TimelineEvent = AgentEvent & { phase: PhaseKey; variants?: string[] };

/** The phase of every event; a step unknown to this UI joins the phase before it. */
export function withPhases(events: AgentEvent[]): TimelineEvent[] {
  let last: PhaseKey = "analyst";
  return events.map((e) => {
    const phase = phaseOfStep(e.step) ?? last;
    last = phase;
    return { ...e, phase };
  });
}

// ---------------------------------------------------------------------------- the words of an event

/** «problem → fix» at the first arrow outside «quotes» (a figure «300 → 330 ₽» inside a quote stays). */
function splitFix(text: string): [string, string | null] {
  let depth = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === "«") depth += 1;
    else if (ch === "»") depth = Math.max(0, depth - 1);
    else if (ch === "→" && depth === 0) {
      const left = text.slice(0, i).trim();
      const right = text.slice(i + 1).trim();
      if (left && right) return [left, right];
    }
  }
  return [text, null];
}

const count = (s: string, ch: string) => s.split(ch).length - 1;

/** A text cut mid-word or inside a quote (older runs cut the critic's notes at 200 characters), ended cleanly. */
export function mendCut(text: string): string {
  const t = text.trimEnd();
  if (!t) return t;
  const unclosed = count(t, "«") > count(t, "»");
  if (/[.!?»)…]$/.test(t)) return unclosed ? `${t}»` : t;
  if (!unclosed && t.length < 180) return t;
  // back to the last whole word, without a dangling preposition or conjunction («… в среднем» cut → «… в» → «…»)
  const head = (/\s/.test(t) ? t.slice(0, t.search(/\s\S*$/)) : t).replace(/\s+[а-яё]{1,2}$/i, "").replace(/[\s\u00a0—–\-;,:«]+$/, "");
  return `${head}…${count(head, "«") > count(head, "»") ? "»" : ""}`;
}

const TWO_OF: Record<string, string> = {
  "круговая диаграмма": "две круговые диаграммы", "кольцевая диаграмма": "две кольцевые диаграммы",
  "столбчатая диаграмма": "две столбчатые диаграммы", "горизонтальная диаграмма": "две горизонтальные диаграммы",
  "линейный график": "два линейных графика", "диаграмма с областями": "две диаграммы с областями",
  "график с заливкой": "два графика с заливкой", "диаграмма": "две диаграммы",
};
const CHART_NAME = Object.keys(TWO_OF).sort((a, b) => b.length - a.length).join("|");
const TWO_CHARTS = new RegExp(`две диаграммы:\\s*(${CHART_NAME})\\s+и\\s+(${CHART_NAME})`, "gi");
const REDONE = /^переделан\S*\s+по\s+замечаниям\s+критика\s*[—–:-]\s*/i;
const OLD_FORM_RU: Record<string, string> = { "ряд показателей": "ряд чисел", "таймлайн": "хронология", "большая цифра": "большое число", "шаги": "процесс" };
// the form where a designer's line names it: first, or after «— », and followed by «(n)», «,», «.» or the end
const OLD_FORMS = /(?:^|(?<=—\s))(?:ряд показателей|таймлайн|большая цифра|шаги)(?=\s*\(|[,.]|$)/gi;
const FIELD_HEAD = /(^|;\s*|,\s*)(заголовок|вывод|подзаголовок|сноска|пункты|выноска)\s*:\s*(?=«)/gi;

const capital = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

// the slide kinds a model may name in its reasoning («Форма cards позволяет…»), beyond the field names plainTerms knows
const KIND_WORDS: Array<[RegExp, string]> = [
  [/(?<![A-Za-z_])cards?(?![A-Za-z_])/gi, "карточки"],
  [/(?<![A-Za-z_])charts?(?![A-Za-z_])/gi, "диаграмма"],
  [/(?<![A-Za-z_])tables?(?![A-Za-z_])/gi, "таблица"],
  [/(?<![A-Za-z_])timelines?(?![A-Za-z_])/gi, "хронология"],
  [/(?<![A-Za-z_])comparisons?(?![A-Za-z_])/gi, "сравнение"],
  [/(?<![A-Za-z_])image_text(?![A-Za-z_])/gi, "картинка и текст"],
  [/(?<![A-Za-z_])quotes?(?![A-Za-z_])/gi, "цитата"],
  [/(?<![A-Za-z_])agenda(?![A-Za-z_])/gi, "повестка"],
];

// the forms a designer names after «Форма» at the start of its reason: quoted as a name, so the verb agrees with «Форма»
const FORM_NAMES = "большое число|ряд чисел|две колонки|карточки|пункты|список|диаграмма|таблица|хронология|сравнение|картинка и текст|цитата|повестка|процесс";
const FORM_LEAD = new RegExp(`^(\\s*)Форма\\s+«?(${FORM_NAMES})»?(?=[\\s,.])`, "i");

/** The agent's words in the interface's: plainTerms plus the slide kinds the model may leave in English, and the form
 *  it names first quoted: «Формат две колонки позволяет…» → «Форма «две колонки» позволяет…». */
export function plainWords(text: string): string {
  // «Формат» is kept as «Форма» (plainTerms would drop it and leave «Две колонки позволяет…»)
  let out = plainTerms(text.replace(/^(\s*)Формат(?=\s)/, "$1Форма"));
  for (const [re, word] of KIND_WORDS) out = out.replace(re, (m, offset: number) => (offset === 0 && /^[A-Z]/.test(m) ? capital(word) : word));
  return out.replace(FORM_LEAD, (_m, sp: string, name: string) => `${sp}Форма «${name.toLowerCase()}»`);
}

/** A line that wraps well: a dash never starts a line, a short preposition or conjunction never ends one («титул и
 *  5 слайдов»), a number stays with its word («6 категорий»), its unit («300 ₽», «25 %») and its own digit groups
 *  («780 000 рублей» and «1 138 500» never break). */
export const keepTogether = (s: string) =>
  s
    .replace(/ ([—–]) /g, "\u00a0$1 ")
    .replace(/(?<=^|[\s(«])(в|во|и|к|ко|с|со|у|о|об|а|на|по|до|из|от|за|не) /gi, "$1\u00a0")
    .replace(/(\d) (?=\d{3}(?!\d))/g, "$1\u00a0")
    .replace(/(\d) (?=[а-яё₽%$€])/gi, "$1\u00a0");

const fullStop = (s: string) => {
  const t = s.replace(/[\s;,:—–-]+$/, "");
  return t && !/[.!?…]$/.test(t) ? `${t}.` : t;
};

/** The critic's «what to do» in words: «Заголовок: «…»; takeaway: «…»» → «Заголовок «…», вывод «…»». A fix that is
 *  only a cut quote («Маркетинговый бюджет…») says nothing and is dropped; a cut last field goes. */
function fixText(fix: string): string | null {
  const t = capital(plainWords(fix).trim().replace(FIELD_HEAD, (_m, sep: string, word: string) => `${sep ? ", " : ""}${word} `));
  if (/^«[^«»]*…»$/.test(t)) return null;
  return t.replace(/,\s*вывод\s*«[^«»]*…»$/, "") || null;
}

/** The words an event shows: the slide's number goes to the badge, the critic's fix goes to its own line, English
 *  field names and «бриф» become the interface's words. Servers since the redesign send it clean; older runs are
 *  cleaned here the same way. */
export function eventParts(e: AgentEvent): { text: string; fix: string | null } {
  let text = mendCut(e.slide !== null && e.slide !== undefined ? e.message.replace(/^слайд[ыа]?\s*\d+\s*[—–:.-]\s*/i, "") : e.message);
  let fix = e.fix ? fixText(e.fix) : null;
  const step = (e.step ?? "").toLowerCase();
  if (step === "critic" && !fix) {
    const [problem, said] = splitFix(text);
    if (said) {
      text = fullStop(problem);
      fix = fixText(said);
    }
  }
  if (step === "designer" || step === "revise" || step === "compile") {
    // older runs named the forms otherwise than the tabs («ряд показателей (3 числа)», «таймлайн (5)»)
    text = text.replace(OLD_FORMS, (m: string) => (/^[А-ЯЁ]/.test(m) ? capital(OLD_FORM_RU[m.toLowerCase()]) : OLD_FORM_RU[m.toLowerCase()]));
    text = text.replace(TWO_CHARTS, (_m, a: string, b: string) => (a.toLowerCase() === b.toLowerCase() ? TWO_OF[a.toLowerCase()] : `${a} и ${b}`));
    const stripped = text.replace(REDONE, "");
    if (stripped !== text && stripped) text = stripped;
  }
  // older runs: «Модель добавила 0 рядов данных и 1 таблицу» says only what was added
  if (step === "analyst") text = text.replace(/(^|\s)0\s+(?:рядов данных|таблиц)\s+и\s+/i, "$1").replace(/\s+и\s+0\s+(?:рядов данных|таблиц)(?=[.\s]*$)/i, "");
  return { text: keepTogether(capital(plainWords(text)) || e.message), fix: fix && keepTogether(fix) };
}

/** «Слайд 3 — круговая диаграмма расходов» with the slide shown as a badge: the text after the number. */
export function eventText(e: AgentEvent): string {
  return eventParts(e).text;
}

// ---------------------------------------------------------------------------- the timeline

export interface TimelineRow {
  key: PhaseKey;
  title: string;
  hint: string;
  status: PhaseStatus;
  /** A short line next to the title: what the step came to («7 замечаний · слайды 2, 4, 5, 6»), the layout progress,
   *  why it was skipped. */
  note: string | null;
  events: TimelineEvent[];
}

export interface TimelineInput {
  events: AgentEvent[];
  /** The latest phase reached (from every event of the job); null before the first one. */
  phase: PhaseKey | null;
  /** The job is still running (false: everything reached is done). */
  running: boolean;
  notes?: Partial<Record<PhaseKey, string | null>>;
}

/** The critic's count line («3 замечания — слайды 2, 4, 5.»): the step's header says it instead. */
const CRITIC_COUNT = /^\d+\s+замечани/;
/** Compile lines that repeat what the rows already show. */
const COMPILE_ECHO = /^(план готов|подготовил данные для диаграмм)/i;

const agrees = (n: number, one: string, many: string) => (n % 10 === 1 && n % 100 !== 11 ? one : many);

/** Lines of one phase that say the same thing about the same slide for several variants become one line; `variants`
 *  names them only when the line does not hold for every variant of the job. */
function mergeVariants(events: TimelineEvent[], allVariants: string[]): TimelineEvent[] {
  const out: TimelineEvent[] = [];
  const byKey = new Map<string, TimelineEvent>();
  for (const e of events) {
    if (!e.variant) {
      out.push(e);
      continue;
    }
    const key = `${e.phase}|${e.slide ?? ""}|${eventText(e)}`;
    const seen = byKey.get(key);
    if (seen) {
      if (!seen.variants?.includes(e.variant)) seen.variants = [...(seen.variants ?? []), e.variant];
      continue;
    }
    const merged: TimelineEvent = { ...e, variants: [e.variant] };
    byKey.set(key, merged);
    out.push(merged);
  }
  return out.map((e) => {
    if (!e.variants) return e;
    const all = allVariants.length > 1 && allVariants.every((v) => e.variants?.includes(v));
    return all || allVariants.length <= 1 ? { ...e, variants: undefined } : e;
  });
}

/** Consecutive lines about one slide share its badge (the critic's notes, the layout's lines of a slide), live and
 *  finished alike: a line about the slide of the line before it goes under that line, without a badge of its own. */
export function slideGroups<T extends AgentEvent>(events: T[]): Array<{ slide: number | null; events: T[] }> {
  const groups: Array<{ slide: number | null; events: T[] }> = [];
  for (const e of events) {
    const slide = e.slide ?? null;
    const last = groups[groups.length - 1];
    if (last && slide !== null && last.slide === slide) last.events.push(e);
    else groups.push({ slide, events: [e] });
  }
  return groups;
}

const slideList = (slides: number[]) => (slides.length === 1 ? `слайд ${slides[0]}` : `слайды ${slides.join(", ")}`);
const uniqueSlides = (events: AgentEvent[]) => [...new Set(events.map((e) => e.slide).filter((n): n is number => typeof n === "number"))].sort((a, b) => a - b);

/** What a step came to, in a few words next to its title. */
function ownNote(key: PhaseKey, events: TimelineEvent[]): string | null {
  const slides = uniqueSlides(events);
  if (key === "designer" && slides.length) return plural(slides.length, "слайд", "слайда", "слайдов");
  if (key === "critic") {
    const notes = events.filter((e) => e.slide !== null && e.slide !== undefined);
    return notes.length ? `${plural(notes.length, "замечание", "замечания", "замечаний")} · ${slideList(slides)}` : null;
  }
  if (key === "revise" && slides.length) return `${plural(slides.length, "слайд", "слайда", "слайдов")} ${agrees(slides.length, "переделан", "переделаны")}`;
  return null;
}

export function buildTimeline({ events, phase, running, notes }: TimelineInput): TimelineRow[] {
  const evs = withPhases(events);
  const allVariants = [...new Set(evs.map((e) => e.variant).filter((v): v is string => !!v))];
  let cur = phase;
  for (const e of evs) cur = laterPhase(cur, e.phase);
  const curIdx = cur ? ORDER[cur] : 0;
  const criticSaid = evs.some((e) => e.phase === "critic");
  const rows: TimelineRow[] = [];
  for (const def of PHASES) {
    let own = mergeVariants(
      evs.filter((e) => e.phase === def.key && !(def.key === "critic" && (e.slide === null || e.slide === undefined) && CRITIC_COUNT.test(eventText(e)))),
      allVariants,
    );
    // the model critic's «Замечаний нет» for the variant contradicts the notes on its slides that the plan's own check
    // added: the step says only the notes
    if (def.key === "critic" && own.some((e) => e.slide !== null && e.slide !== undefined)) {
      own = own.filter((e) => (e.slide !== null && e.slide !== undefined) || !/^замечаний нет/i.test(eventText(e)));
    }
    // «Модель добавила 0 таблиц» (older runs) says nothing
    if (def.key === "analyst") own = own.filter((e) => !/^модель добавила\s+0\s/i.test(eventText(e)));
    if (!running) {
      // a finished step reports what it came to, not what it was doing («Уточняю данные слайдов…»)
      if (def.key === "analyst") own = own.filter((e) => !/^уточняю(?![а-яё])/i.test(eventText(e)));
      if (def.key === "layout") own = own.filter((e) => !COMPILE_ECHO.test(eventText(e)));
    }
    // the steps that work slide by slide read in slide order, live too (the designer thinks the slides through in
    // parallel, the critic's notes for three variants arrive interleaved): lines about no slide first, a stable sort
    if (def.key === "designer" || def.key === "critic" || def.key === "revise") {
      own = own.map((e, i) => ({ e, i })).sort((a, b) => (a.e.slide ?? 0) - (b.e.slide ?? 0) || a.i - b.i).map(({ e }) => e);
    }
    const hadAny = evs.some((e) => e.phase === def.key);
    if (def.optional && !hadAny) continue;
    const idx = ORDER[def.key];
    const passed = running ? idx < curIdx : idx <= curIdx || !cur;
    let status: PhaseStatus = passed ? "done" : running && idx === curIdx ? "active" : "pending";
    let note = notes?.[def.key] ?? ownNote(def.key, own);
    // the critic and the revision leave no trace when the plan came without the model, ran out of time or needed no fixes
    if ((def.key === "critic" || def.key === "revise") && !hadAny && passed) {
      status = "skipped";
      note = def.key === "critic" ? "в этой сборке не запускался" : criticSaid ? "правки не понадобились" : "не понадобилась";
    }
    rows.push({ key: def.key, title: def.title, hint: def.hint, status, note, events: own });
  }
  return rows;
}

// ---------------------------------------------------------------------------- a finished variant

/** What the deck shows, counted: «4 диаграммы, 1 таблица, 1 формула». */
export function formsSummary(outline: DeckOutline | null | undefined): string | null {
  if (!outline) return null;
  let charts = 0;
  let tables = 0;
  let formulas = 0;
  for (const s of outline.slides) {
    charts += (s.content.chart ? 1 : 0) + (s.content.chart2 ? 1 : 0);
    tables += s.content.table ? 1 : 0;
    formulas += s.content.formula ? 1 : 0;
  }
  const parts = [charts && plural(charts, "диаграмма", "диаграммы", "диаграмм"), tables && plural(tables, "таблица", "таблицы", "таблиц"), formulas && plural(formulas, "формула", "формулы", "формул")].filter(Boolean);
  return parts.length ? parts.join(", ") : null;
}

export interface AgentSummaryLine { step: string; text: string }

const noStop = (s: string) => s.replace(/[.\s]+$/, "");

/** Three lines for the result screen: what the analyst found, what the designer made, what the critic said. */
export function agentSummary(v: Variant | null | undefined): AgentSummaryLine[] {
  const a = v?.agent;
  if (!a) return [];
  const evs = withPhases(a.events ?? []);
  const lines: AgentSummaryLine[] = [];
  if (evs.length) {
    // the analyst's last word is its result («Нашёл в тексте 5 слайдов…»), not «Уточняю данные…»
    const results = evs.filter((e) => e.phase === "analyst" && !/^(уточняю|модель добавила)(?![а-яё])/i.test(eventText(e)));
    const analyst = results.filter((e) => /^нашёл/i.test(eventText(e))).pop() ?? results.pop();
    // «Нашёл 5 слайдов, 11 рядов данных и 7 диаграмм»: the card's two lines hold the whole finding
    const found = analyst ? noStop(eventText(analyst).replace(/^нашёл\s+в\s+тексте\s+/i, "Нашёл ").replace(/\s+заказанн\S*/gi, "")) : null;
    if (found) lines.push({ step: "Аналитик", text: found });
    const designed = evs.filter((e) => e.phase === "designer");
    const designedSlides = uniqueSlides(designed).length || designed.length;
    const forms = formsSummary(v?.outline);
    // the analyst counts the text's slides, the designer adds the title slide in front: «5 слайдов» and «6 слайдов» on
    // two lines read as a contradiction, «титул и 5 слайдов» says both
    const inText = Number(found?.match(/(\d+)(?:\s|\u00a0)+слайд/)?.[1] ?? NaN);
    const withTitle = inText > 0 && inText === designedSlides - 1 && v?.outline?.slides[0]?.kind === "title";
    const made = withTitle ? `титул и ${plural(inText, "слайд", "слайда", "слайдов")}` : plural(designedSlides, "слайд", "слайда", "слайдов");
    if (designed.length) lines.push({ step: "Дизайнер", text: `Продумал ${made}${forms ? `: ${forms}` : ""}` });
    const mine = (e: AgentEvent) => e.variant == null || e.variant === v?.strategy;
    const critic = evs.filter((e) => e.phase === "critic" && mine(e));
    const said = critic.filter((e) => e.slide !== null && e.slide !== undefined).length;
    const fixed = uniqueSlides(evs.filter((e) => e.phase === "revise" && mine(e))).length;
    if (critic.length || fixed) {
      const skipped = !said && critic.find((e) => /пропущен|не ответил|не запускал/i.test(e.message));
      const text = skipped
        ? noStop(eventText(skipped))
        : said || fixed
          ? [said ? plural(said, "замечание", "замечания", "замечаний") : null, fixed ? `${agrees(fixed, "исправлен", "исправлено")} ${plural(fixed, "слайд", "слайда", "слайдов")}` : null].filter(Boolean).join(", ")
          : "Замечаний нет";
      lines.push({ step: "Критик", text: capital(text) });
    }
    return lines.map((l) => ({ ...l, text: keepTogether(l.text) }));
  }
  // older runs: the log's first lines, without their full stops (the card's lines are labels, not sentences)
  return (a.log ?? []).slice(0, 3).map((line) => {
    const m = line.match(/^([А-ЯЁ][а-яё]+):\s*(.+)$/);
    return m ? { step: m[1], text: keepTogether(capital(noStop(plainTerms(m[2])))) } : { step: "", text: keepTogether(noStop(plainTerms(line))) };
  });
}

/** The sentence the agent says when the text dictated every slide's form: the variants differ only in how they present
 *  it (a tooltip of the result's variant switch). */
export function variantsNote(v: Variant | null | undefined): string | null {
  const a = v?.agent;
  if (!a) return null;
  const same = [...(a.events ?? []).map((e) => e.message), ...(a.log ?? [])].find((m) => /отличаются подачей/.test(m));
  return same ? plainTerms(same.replace(/^Сборка:\s*/, "")) : null;
}

export const hasAgentWork = (v: Variant | null | undefined) => !!v?.agent && ((v.agent.events?.length ?? 0) > 0 || (v.agent.log?.length ?? 0) > 0);
