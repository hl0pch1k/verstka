// «Почему так»: first the designer's own reason for the form of the slide, the other forms it proposed (one of them
// may be the form another variant shows) and the critic's notes with their fixes; then how the slide was laid out in
// the template, other layouts that also fit (for slides cloned from a sample) and the slide's quality check in a row.
import { useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronLeft, ChevronRight } from "lucide-react";
import { eventParts, plainWords } from "../../lib/agent";
import { slideCount } from "../../lib/narrate";
import { humanReasons } from "../../lib/reasons";
import { cn, KIND_LABEL, kindLabel, plural } from "../../lib/utils";
import { useApp } from "../../store";
import type { OutlineSlide, Pattern, SlideAlternativeInfo, Variant } from "../../types";
import { isMinor } from "../AuditHelpers";
import { Button } from "../ui/Button";
import { Progress } from "../ui/Progress";
import { issuesBySlide, planEntryFor, variantRev, withRev } from "../VariantsHelpers";

const CARD = "rounded-2xl bg-white p-6 shadow-card";

function Frame({ src, label, aspect }: { src: string | null; label: string; aspect: number }) {
  const [broken, setBroken] = useState(false);
  return (
    <figure className="min-w-0 flex-1">
      <div className="overflow-hidden rounded-xl bg-zinc-100 ring-1 ring-zinc-900/[0.08]" style={{ aspectRatio: String(aspect) }}>
        {src && !broken ? (
          <img src={src} alt={label} draggable={false} onError={() => setBroken(true)} className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full items-center justify-center px-4 text-center text-caption text-zinc-500">Превью не сохранилось</div>
        )}
      </div>
      <figcaption className="mt-2 text-caption text-zinc-500">{label}</figcaption>
    </figure>
  );
}

const capital = (t: string) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);

// «столбчатая диаграмма: График позволит…» (a chart type in front of the reason): the type is the form's name
const CHART_HEAD = /^((?:[а-яё]+\s+)?(?:диаграмма|график)(?:\s+с\s+[а-яё]+)?)\s*:\s*(.+)$/is;
// an adjective in front of the noun it describes («статистический ряд», «краткий список», «круговая диаграмма»)
const ADJECTIVE = /(?:ий|ый|ой|ая|яя|ое|ее|ые|ие)$/i;
const NUMERAL = /^(?:два|две|три|четыре)$/i;
const CHART_NOUNS = ["диаграмма", "график"];

/** «таблица» and «таблицей», «ряд» and «ряда»: one word in another case; «табличное» is another word. */
function sameWord(a: string, b: string): boolean {
  const x = a.toLowerCase();
  const y = b.toLowerCase();
  const stem = y.length <= 4 ? y : y.slice(0, -1);
  return x.startsWith(stem) && x.length <= y.length + 2;
}

/** The noun a verb agrees with: masculine, feminine, neuter or plural, by its ending. */
type Agreement = "m" | "f" | "n" | "p";
const agreementOf = (noun: string): Agreement => (/[ыи]$/i.test(noun) ? "p" : /[ая]$/i.test(noun) ? "f" : /[оеё]$/i.test(noun) ? "n" : "m");
const PAST: Record<Agreement, string> = { m: "л", f: "ла", n: "ло", p: "ли" };
const VERB = /^(?:[а-яё]*[аеиоуяы](?:л|ла|ло|ли)|[а-яё]+(?:ет|ёт|ит|ют|ят|ут))$/i;

/** A verb said of one noun, said of another: «график показал» → «(диаграмма) показала», «форма позволяет» →
 *  «(карточки) позволяют». */
function agree(verb: string, from: Agreement, to: Agreement): string {
  if (from === to) return verb;
  const past = /^([а-яё]*[аеиоуяы])(?:л|ла|ло|ли)$/i.exec(verb);
  if (past) return past[1] + PAST[to];
  if (to === "p" && from !== "p") {
    if (/^может$/i.test(verb)) return "могут";
    if (/[аеиоуяю]ет$/i.test(verb) || /ёт$/i.test(verb)) return verb.replace(/[её]т$/i, "ют");
    if (/ит$/i.test(verb)) return verb.replace(/ит$/i, "ят");
  }
  return verb;
}

/** The reason told after the form's name: without a leading repeat of the name («Таблица позволит…», «Статистический
 *  ряд покажет…», «Форма «карточки» позволяет…», «График позволит…» after «столбчатая диаграмма») and with its verb
 *  agreeing with the name, from a small letter (an acronym keeps its capitals) and, when it is one sentence, without
 *  its full stop. */
function reasonAfter(label: string, text: string): string {
  let t = text.trim();
  const words = label.toLowerCase().split(/\s+/).filter(Boolean);
  const head = words.find((w) => !ADJECTIVE.test(w) && !NUMERAL.test(w)) ?? words[words.length - 1] ?? "";
  // the subject the reason was written for, when it is not the name itself
  let subject: Agreement | null = null;
  const form = /^Форма\s+«[^«»]+»\s*/i.exec(t);
  if (form) {
    t = t.slice(form[0].length);
    subject = "f";
  } else if (label && t.toLowerCase().startsWith(label.toLowerCase()) && !/^[а-яёa-z0-9]/i.test(t.slice(label.length))) {
    t = t.slice(label.length);
  } else if (head) {
    const m = /^(?:([а-яё]+)\s+)?([а-яё]+)(?=[\s,.:—–-]|$)/i.exec(t);
    if (m) {
      // «Статистический ряд …»: the adjective goes with its noun; «Ряд …»: the noun alone
      const [lead, noun] = m[1] && ADJECTIVE.test(m[1]) ? [m[0], m[2]] : [m[1] ?? m[2], m[1] ?? m[2]];
      const synonyms = CHART_NOUNS.includes(head) ? CHART_NOUNS : [head];
      // «График столбцов поможет…»: a noun that takes the next word with it stays whole
      const next = /^\s+([а-яё]+)/i.exec(t.slice(lead.length))?.[1] ?? "";
      if (synonyms.some((w) => sameWord(noun, w)) && !/(?:ов|ев|ей)$/i.test(next)) {
        t = t.slice(lead.length);
        subject = agreementOf(noun);
      }
    }
  }
  t = t.replace(/^[\s,:;—–-]+/, "");
  // «(Таблица) бы ясно показала…» → «ясно показала бы…»; the verb agrees with the name
  const lone = /^бы\s+/i.exec(t);
  if (lone) t = t.slice(lone[0].length);
  const parts = t.split(" ");
  const at = parts.slice(0, 3).findIndex((w) => VERB.test(w));
  // «Позволяет визуализировать…», «Визуально выделит…» said of plural «Карточки»: the reason's own subject is left out
  // («форма»), its verb is singular
  if (!subject && at >= 0 && (at === 0 || (at === 1 && /о$/i.test(parts[0]))) && agreementOf(head) === "p" && /(?:ет|ёт|ит)$/i.test(parts[at])) subject = "f";
  if (at >= 0) {
    if (subject) {
      const to = agreementOf(head);
      parts[at] = agree(parts[at], subject, to);
      // «…позволяют разделить цель и меры, соответствует стилю и позволяет…»: the present-tense verbs joined to the
      // first one by a comma or «и» share its subject (a «что делает…» clause has its own; «и доли» is a noun)
      for (let i = at + 1; i < parts.length; i++) {
        if (/^[а-яё]{4,}(?:ет|ёт|ит)$/i.test(parts[i]) && (/,$/.test(parts[i - 1]) || /^и$/i.test(parts[i - 1]))) parts[i] = agree(parts[i], subject, to);
      }
    }
    if (lone) parts[at] += " бы";
    t = parts.join(" ");
  } else if (lone) t = `бы ${t}`;
  if (/^[А-ЯЁA-Z][а-яёa-z]/.test(t)) t = t.charAt(0).toLowerCase() + t.slice(1);
  if (/[^.]\.$/.test(t) && !/[.!?…]\s/.test(t.slice(0, -1))) t = t.slice(0, -1);
  return t;
}

/** An alternative form in the interface's words: the slide kinds named as the tabs name them («Ряд чисел», a chart type
 *  the reason starts with taken for the name) and the reason told after the name, the same way on every row. */
function altWords(a: SlideAlternativeInfo): { label: string; text: string } {
  let label = a.kind && KIND_LABEL[a.kind] ? kindLabel(a.kind) : a.label ?? "";
  let text = a.text ? plainWords(a.text) : "";
  const m = CHART_HEAD.exec(text);
  if (m) {
    label = m[1].toLowerCase();
    text = m[2];
  }
  return label ? { label: capital(label), text: reasonAfter(label, text) } : { label: "", text: capital(text.trim()) };
}

/** What the slide designer said about the slide: why this form, the other forms, the conclusion, the critic's notes. */
function DesignNote({ v, index }: { v: Variant; index: number }) {
  const { strategyTitle, setActiveStrategy } = useApp();
  const d = v.design?.find((x) => x.index === index) ?? null;
  const o = v.outline?.slides[index - 1] ?? null;
  const rationale = d?.rationale ?? o?.rationale ?? null;
  const alts: SlideAlternativeInfo[] = d?.alternatives ?? (o?.alternatives ?? []).map((a) => ({ kind: a.kind || null, label: null, text: a.change || null }));
  const takeaway = d?.takeaway ?? o?.takeaway ?? null;
  const footnote = d?.footnote ?? o?.footnote ?? null;
  const spec = d?.spec_ref ?? o?.spec_ref ?? null;
  const notes = (v.agent?.critic ?? []).filter((e) => e.slide === index);
  if (!rationale && alts.length === 0 && notes.length === 0 && !takeaway) return null;
  return (
    <section className={cn(CARD, "animate-fade-in")}>
      <div className="flex items-baseline gap-3">
        <h3 className="text-title3 font-semibold text-zinc-900">Почему такая форма</h3>
        {spec !== null && spec !== index && <span className="text-footnote text-zinc-500">В вашем тексте — слайд {spec}</span>}
      </div>
      {rationale && <p className="mt-2 max-w-[680px] text-body leading-6 text-zinc-900">{plainWords(rationale)}</p>}
      {(takeaway || footnote) && (
        <dl className="mt-4 grid max-w-[680px] grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-footnote">
          {takeaway && (
            <>
              <dt className="font-semibold text-zinc-700">Вывод</dt>
              <dd className="text-zinc-700">{takeaway}</dd>
            </>
          )}
          {footnote && (
            <>
              <dt className="font-semibold text-zinc-700">Сноска</dt>
              <dd className="text-zinc-700">{footnote}</dd>
            </>
          )}
        </dl>
      )}
      {alts.length > 0 && (
        <div className="mt-6">
          <h4 className="text-footnote font-semibold text-zinc-900">Другие формы</h4>
          <ul className="mt-2 space-y-2">
            {alts.map((a, i) => {
              const { label, text } = altWords(a);
              const used = (a.used_in ?? []).filter((s) => s !== v.strategy);
              return (
                <li key={i} className="flex min-h-14 items-center gap-3 rounded-xl bg-zinc-100 px-4 py-3">
                  {/* every row reads the same: «**Таблица** — позволит увидеть точные значения…» */}
                  <span className="min-w-0 flex-1 text-footnote">
                    {label && <span className="font-semibold text-zinc-900">{label}</span>}
                    {label && text && <span className="text-zinc-500">{"\u00a0— "}</span>}
                    {text && <span className="text-zinc-700">{text}</span>}
                  </span>
                  {used.length > 0 && (
                    <Button variant="white" size="sm" iconRight={ArrowRight} onClick={() => setActiveStrategy(used[0])} title="Переключиться на этот вариант">
                      {strategyTitle(used[0])}
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {notes.length > 0 && (
        <div className="mt-6">
          <h4 className="text-footnote font-semibold text-zinc-900">Критик и правка</h4>
          <ul className="mt-2 space-y-2">
            {notes.map((e, i) => {
              const { text, fix } = eventParts(e);
              const revise = e.step === "revise";
              return (
                <li key={e.seq ?? i} className="flex items-start gap-3 text-footnote">
                  <span className={cn("inline-flex h-5 min-w-[72px] shrink-0 items-center justify-center rounded-lg px-2 text-caption font-semibold", revise ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700")}>
                    {revise ? "Правка" : "Критик"}
                  </span>
                  <div className="min-w-0 max-w-[680px] flex-1">
                    <p className="text-zinc-700">{text}</p>
                    {fix && (
                      <p className="mt-1 flex gap-1 text-zinc-500">
                        <ArrowRight className="mt-[3px] h-3.5 w-3.5 shrink-0 text-zinc-400" aria-hidden />
                        <span className="min-w-0">
                          <span className="sr-only">Исправление: </span>
                          {fix}
                        </span>
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}

/** A composed slide shows the template's nearest sample only when that sample is the same kind of slide (a chart
 *  sample of another chart type would mislead). */
const sameKind = (p: Pattern | null, s: OutlineSlide | null) => !!p && !!s && p.kind === s.kind && s.kind !== "chart";

export function WhySlide() {
  const { generation, activeVariant, selectedSlide, setSelectedSlide, manifest, strategyTitle, setDetail } = useApp();
  const v = activeVariant ?? generation?.variants[0];
  if (!generation || !v) return null;
  const total = slideCount(v);
  const rev = variantRev(v);
  const entry = planEntryFor(v, selectedSlide);
  const templateOk = !!manifest && manifest.template_id === generation.template_id;
  const patternById = (id: string | null | undefined): Pattern | null => (templateOk && id ? manifest.patterns.find((p) => p.id === id) ?? null : null);
  const outlineSlide = v.outline?.slides[selectedSlide - 1] ?? null;
  const composed = entry?.mode === "synth";
  const pattern = entry?.mode === "clone" ? patternById(entry.pattern_id) : null;
  const nearestRaw = composed ? patternById(entry?.alternatives[0]?.[0]) : null;
  const nearest = sameKind(nearestRaw, outlineSlide) ? nearestRaw : null;
  const sample = pattern ?? nearest;
  const aspect = templateOk ? manifest.slide_size.w / manifest.slide_size.h : 16 / 9;
  const own = v.slides[selectedSlide - 1] ? withRev(v.slides[selectedSlide - 1], rev) : null;
  const issues = (issuesBySlide(v.audit).get(selectedSlide) ?? []).filter((i) => !isMinor(i));
  const worst = issues.some((i) => i.severity === "error") ? "error" : issues.length ? "warn" : null;
  const reasons = entry ? humanReasons(entry.reasons, strategyTitle, (pid) => patternById(pid)?.source_slide ?? null) : [];
  const match = entry && !composed ? Math.round(Math.min(1, Math.max(0, entry.score)) * 100) : null;
  const others = (entry?.alternatives ?? []).filter(([pid]) => pid !== entry?.pattern_id).map(([, s]) => s);
  const runnerUp = others.length ? Math.round(Math.min(1, Math.max(0, Math.max(...others))) * 100) : null;
  const alternatives = composed
    ? []
    : (entry?.alternatives ?? [])
        .map(([pid, score]) => ({ p: patternById(pid), score }))
        .filter((a): a is { p: Pattern; score: number } => !!a.p && a.score > 0.05 && a.p.id !== pattern?.id)
        .slice(0, 3);
  // one or two layouts take half the width each, three a third: a lone sample never stretches across the card
  const COLS = ["grid-cols-2", "grid-cols-2", "grid-cols-3"];

  return (
    <div>
      <nav aria-label="Слайд" className="sticky -top-6 z-10 -mx-6 -mt-6 mb-4 flex items-center gap-3 border-b border-zinc-200/70 bg-canvas/95 px-6 py-3 backdrop-blur">
        <Button variant="ghost" shape="circle" size="md" icon={ChevronLeft} aria-label="Предыдущий слайд" disabled={selectedSlide <= 1} onClick={() => setSelectedSlide(selectedSlide - 1)} />
        <div className="min-w-0 flex-1 text-center">
          <p className="text-caption text-zinc-500">
            Слайд {selectedSlide} / {total}
            {outlineSlide ? ` · ${kindLabel(outlineSlide.kind)}` : ""}
          </p>
          <p className="line-clamp-1 text-body font-semibold text-zinc-900" title={outlineSlide?.headline || undefined}>
            {outlineSlide?.headline || "Без заголовка"}
          </p>
        </div>
        <Button variant="ghost" shape="circle" size="md" icon={ChevronRight} aria-label="Следующий слайд" disabled={selectedSlide >= total} onClick={() => setSelectedSlide(selectedSlide + 1)} />
      </nav>

      <div className="space-y-4">
        <DesignNote key={`d${selectedSlide}/${v.strategy}`} v={v} index={selectedSlide} />

        <section key={`${selectedSlide}/${rev}`} className={cn(CARD, "animate-fade-in")}>
          <h3 className="text-title3 font-semibold text-zinc-900">Как собран слайд</h3>
          {sample ? (
            <div className="mt-4 flex items-center gap-4">
              <Frame src={sample.thumbnail_url ?? null} label={pattern ? `Образец: слайд ${sample.source_slide} шаблона` : `Ближайший образец: слайд ${sample.source_slide} шаблона`} aspect={aspect} />
              <ArrowRight className="mb-6 h-5 w-5 shrink-0 text-zinc-400" aria-hidden />
              <Frame src={own} label="Ваш слайд" aspect={aspect} />
            </div>
          ) : (
            <div className="mt-4">
              <Frame src={own} label={composed ? "Собран по сетке, шрифтам и цветам шаблона" : "Ваш слайд"} aspect={aspect} />
            </div>
          )}
          {match !== null && (
            <div className="mt-6">
              <div className="flex items-baseline justify-between text-footnote">
                <span className="font-semibold text-zinc-700">Сходство с образцом</span>
                <span className="font-semibold tabular-nums text-zinc-900">{match}%</span>
              </div>
              <Progress size="md" value={match / 100} tone={!pattern ? "neutral" : match >= 70 ? "success" : "accent"} className="mt-2" />
              <p className="mt-2 text-footnote text-zinc-500">
                {!pattern
                  ? "Ни один образец не подошёл достаточно хорошо — слайд собран с нуля в стиле шаблона"
                  : runnerUp === null
                    ? "Единственный макет шаблона, подходящий для такого слайда"
                    : runnerUp <= match
                      ? `Лучший из рассмотренных: у остальных сходство ${runnerUp}% и ниже`
                      : entry?.reasons.some((r) => r.startsWith("автофикс:"))
                        ? `Заменён проверкой качества: макет со сходством ${runnerUp}% дал замечания`
                        : "Выбран с учётом стиля варианта и соседних слайдов"}
              </p>
            </div>
          )}
          {reasons.length > 0 && (
            <ul className="mt-6 max-w-[680px] space-y-2">
              {reasons.map((r) => (
                <li key={r.text} className="flex items-start gap-3 text-footnote text-zinc-700">
                  {r.good ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" aria-hidden /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" aria-hidden />}
                  {r.text}
                </li>
              ))}
            </ul>
          )}
        </section>

        {alternatives.length > 0 && (
          <section className={CARD}>
            <h3 className="text-title3 font-semibold text-zinc-900">Другие подходящие макеты</h3>
            <div className={cn("mt-4 grid gap-4", COLS[alternatives.length - 1])}>
              {alternatives.map(({ p, score }) => (
                <figure key={p.id} className="min-w-0">
                  <div className="overflow-hidden rounded-xl bg-zinc-100 ring-1 ring-zinc-900/[0.08]" style={{ aspectRatio: String(aspect) }}>
                    {p.thumbnail_url && <img src={p.thumbnail_url} alt="" loading="lazy" draggable={false} className="h-full w-full object-cover" />}
                  </div>
                  <figcaption className="mt-2 flex items-baseline justify-between gap-2 text-caption text-zinc-500">
                    <span className="truncate" title={`Слайд ${p.source_slide} шаблона · ${kindLabel(p.kind)}`}>
                      Слайд {p.source_slide} · {kindLabel(p.kind)}
                    </span>
                    <span className="shrink-0 tabular-nums">сходство {Math.round(score * 100)}%</span>
                  </figcaption>
                </figure>
              ))}
            </div>
          </section>
        )}

        {!v.audit ? (
          <div className="flex h-12 items-center gap-3 rounded-2xl bg-white px-6 text-body text-zinc-500 shadow-card">Проверка слайда не запускалась</div>
        ) : worst === null ? (
          <div className="flex h-12 items-center gap-3 rounded-2xl bg-white px-6 text-body text-zinc-900 shadow-card">
            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" aria-hidden />
            <span>
              Проверка слайда <span className="text-zinc-500">· замечаний нет</span>
            </span>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setDetail("quality")}
            className="flex h-12 w-full cursor-pointer items-center gap-3 rounded-2xl bg-white px-6 text-left text-body text-zinc-900 shadow-card transition-colors duration-150 hover:bg-zinc-50"
          >
            <AlertTriangle className={cn("h-4 w-4 shrink-0", worst === "error" ? "text-red-500" : "text-amber-500")} aria-hidden />
            <span>
              Проверка слайда <span className={worst === "error" ? "text-red-600" : "text-amber-700"}>· {plural(issues.length, "замечание", "замечания", "замечаний")}</span>
            </span>
            <ChevronRight className="ml-auto h-4 w-4 shrink-0 text-zinc-400" aria-hidden />
          </button>
        )}
      </div>
    </div>
  );
}
