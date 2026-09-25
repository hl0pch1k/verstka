// «Почему слайд такой»: first the designer's own reason for the form of the slide and the other forms it proposed
// (Agent v2; one of them may be the form another variant shows), with the critic's notes on it; then the sample of
// the template next to the slide made from it, the reasons of the layout in words, other layouts that also fit, and
// the remarks of the quality check. The raw trace stays folded below.
import { useState } from "react";
import { ArrowRight, Check, ChevronLeft, ChevronRight, Lightbulb, Minus } from "lucide-react";
import { eventText } from "../../lib/agent";
import { slideCount } from "../../lib/narrate";
import { humanReasons } from "../../lib/reasons";
import { cn, kindLabel } from "../../lib/utils";
import { useApp } from "../../store";
import type { LayoutSlide, Pattern, SlideAlternativeInfo, Variant } from "../../types";
import { IssueLine } from "../AuditIssues";
import { Button } from "../ui/Button";
import { Collapsible } from "../ui/Collapsible";
import { issuesBySlide, planEntryFor, variantRev, withRev } from "../VariantsHelpers";

function Frame({ src, label, aspect, muted }: { src: string | null; label: string; aspect: number; muted?: boolean }) {
  const [broken, setBroken] = useState(false);
  return (
    <figure className="min-w-0 flex-1">
      <div className={cn("overflow-hidden rounded-xl bg-zinc-100 shadow-inner-line", muted && "opacity-90")} style={{ aspectRatio: String(aspect) }}>
        {src && !broken ? (
          <img src={src} alt={label} draggable={false} onError={() => setBroken(true)} className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full items-center justify-center px-4 text-center text-xs text-zinc-500">{label}</div>
        )}
      </div>
      <figcaption className="mt-2 text-center text-xs font-medium text-zinc-500">{label}</figcaption>
    </figure>
  );
}

/** What the slide designer said about the slide: why this form, the other forms, the conclusion, the critic's notes. */
function DesignNote({ v, index }: { v: Variant; index: number }) {
  const { strategyTitle, setActiveStrategy, generation } = useApp();
  const d = v.design?.find((x) => x.index === index) ?? null;
  const o = v.outline?.slides[index - 1] ?? null;
  const rationale = d?.rationale ?? o?.rationale ?? null;
  const alts: SlideAlternativeInfo[] = d?.alternatives ?? (o?.alternatives ?? []).map((a) => ({ kind: a.kind || null, label: null, text: a.change || null }));
  const takeaway = d?.takeaway ?? o?.takeaway ?? null;
  const footnote = d?.footnote ?? o?.footnote ?? null;
  const spec = d?.spec_ref ?? o?.spec_ref ?? null;
  const notes = (v.agent?.critic ?? []).filter((e) => e.slide === index);
  if (!rationale && alts.length === 0 && notes.length === 0 && !takeaway) return null;
  const variantNo = (name: string) => (generation?.variants.findIndex((x) => x.strategy === name) ?? -1) + 1;
  return (
    <section className="rounded-3xl bg-white p-6 shadow-card animate-fade-in">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-50 text-accent" aria-hidden>
          <Lightbulb className="h-[18px] w-[18px]" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[17px] font-semibold text-zinc-900">Почему такая форма</h3>
          <p className="text-[13px] text-zinc-500">Решение агента-дизайнера{spec ? ` · в вашем тексте это слайд ${spec}` : ""}</p>
        </div>
      </div>
      {rationale && <p className="mt-4 text-[15px] leading-6 text-zinc-800">{rationale}</p>}
      {(takeaway || footnote) && (
        <dl className="mt-3 space-y-1 text-[13px] leading-5">
          {takeaway && (
            <div className="flex gap-2">
              <dt className="shrink-0 font-semibold text-zinc-700">Вывод на слайде:</dt>
              <dd className="text-zinc-600">{takeaway}</dd>
            </div>
          )}
          {footnote && (
            <div className="flex gap-2">
              <dt className="shrink-0 font-semibold text-zinc-700">Сноска:</dt>
              <dd className="text-zinc-600">{footnote}</dd>
            </div>
          )}
        </dl>
      )}
      {alts.length > 0 && (
        <div className="mt-5">
          <p className="text-[13px] font-semibold text-zinc-900">Другие формы, которые агент рассматривал</p>
          <ul className="mt-2 space-y-2">
            {alts.map((a, i) => {
              const label = a.label ?? (a.kind ? kindLabel(a.kind) : null);
              const used = (a.used_in ?? []).filter((s) => s !== v.strategy);
              return (
                <li key={i} className="flex items-center gap-3 rounded-2xl bg-zinc-50 px-4 py-2.5">
                  <span className="min-w-0 flex-1 text-[13px] leading-5">
                    {label && <span className="font-semibold text-zinc-900">{label.charAt(0).toUpperCase() + label.slice(1)}</span>}
                    {label && a.text && <span className="text-zinc-400"> — </span>}
                    {a.text && <span className="text-zinc-600">{a.text}</span>}
                  </span>
                  {used.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setActiveStrategy(used[0])}
                      title="Переключиться на этот вариант"
                      className="shrink-0 cursor-pointer rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-accent-700 shadow-card transition-colors hover:bg-accent-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30"
                    >
                      так в варианте {variantNo(used[0]) || ""} · {strategyTitle(used[0])}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {notes.length > 0 && (
        <div className="mt-5">
          <p className="text-[13px] font-semibold text-zinc-900">Замечания критика и правка</p>
          <ul className="mt-2 space-y-1.5">
            {notes.map((e, i) => (
              <li key={e.seq ?? i} className="flex items-start gap-2.5 text-[13px] leading-5 text-zinc-700">
                <span className={cn("mt-px inline-flex h-5 shrink-0 items-center rounded-md px-1.5 text-[11px] font-semibold", e.step === "revise" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800")}>
                  {e.step === "revise" ? "Правка" : "Критик"}
                </span>
                <span className="min-w-0 flex-1">{eventText(e)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/** The record of the layout plan as the matcher wrote it — for whoever wants to check the reasoning. */
function Trace({ entry }: { entry: LayoutSlide }) {
  const head = [entry.mode === "clone" ? `clone ${entry.pattern_id ?? ""}`.trim() : `synth ${entry.composition ?? ""}`.trim(), `score ${entry.score.toFixed(2)}`];
  return (
    <Collapsible title="Технический след" hint="как это записано в плане раскладки" keepMounted={false}>
      <div className="space-y-2 font-mono text-xs leading-5 text-zinc-600">
        <p>{head.join(" · ")}</p>
        {entry.reasons.length > 0 && (
          <ul className="space-y-0.5">
            {entry.reasons.map((r, i) => <li key={i}>· {r}</li>)}
          </ul>
        )}
        {entry.alternatives.length > 0 && <p className="text-zinc-500">alternatives: {entry.alternatives.slice(0, 5).map(([id, sc]) => `${id} ${sc.toFixed(2)}`).join(", ")}</p>}
      </div>
    </Collapsible>
  );
}

export function WhySlide() {
  const { generation, activeVariant, selectedSlide, setSelectedSlide, manifest, strategyTitle } = useApp();
  const v = activeVariant ?? generation?.variants[0];
  if (!generation || !v) return null;
  const total = slideCount(v);
  const rev = variantRev(v);
  const entry = planEntryFor(v, selectedSlide);
  const templateOk = !!manifest && manifest.template_id === generation.template_id;
  const patternById = (id: string | null | undefined): Pattern | null => (templateOk && id ? manifest.patterns.find((p) => p.id === id) ?? null : null);
  const pattern = entry?.mode === "clone" ? patternById(entry.pattern_id) : null;
  // a composed slide shows the template's nearest sample next to it: same style, geometry fitted to the content
  const nearest = entry?.mode === "synth" ? patternById(entry.alternatives[0]?.[0]) : null;
  const composed = entry?.mode === "synth";
  const aspect = templateOk ? manifest.slide_size.w / manifest.slide_size.h : 16 / 9;
  const outlineSlide = v.outline?.slides[selectedSlide - 1] ?? null;
  const own = v.slides[selectedSlide - 1] ? withRev(v.slides[selectedSlide - 1], rev) : null;
  const issues = issuesBySlide(v.audit).get(selectedSlide) ?? [];
  const reasons = entry ? humanReasons(entry.reasons, strategyTitle, (pid) => patternById(pid)?.source_slide ?? null) : [];
  const match = entry ? Math.round(Math.min(1, Math.max(0, entry.score)) * 100) : null;
  const others = (entry?.alternatives ?? []).filter(([pid]) => pid !== entry?.pattern_id).map(([, s]) => s);
  const runnerUp = others.length ? Math.round(Math.min(1, Math.max(0, Math.max(...others))) * 100) : null;
  const alternatives = (entry?.alternatives ?? [])
    .map(([pid, score]) => ({ p: patternById(pid), score }))
    .filter((a): a is { p: Pattern; score: number } => !!a.p && a.score > 0.05 && a.p.id !== pattern?.id && a.p.id !== nearest?.id)
    .slice(0, 3);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 rounded-2xl bg-white px-4 py-3 shadow-card">
        <Button icon={ChevronLeft} aria-label="Предыдущий слайд" disabled={selectedSlide <= 1} onClick={() => setSelectedSlide(selectedSlide - 1)} className="rounded-full" />
        <div className="min-w-0 flex-1 text-center">
          <p className="text-xs text-zinc-500">
            Слайд {selectedSlide} из {total}
            {outlineSlide ? ` · ${kindLabel(outlineSlide.kind)}` : ""}
          </p>
          <p className="truncate text-[15px] font-semibold text-zinc-900">{outlineSlide?.headline || "Без заголовка"}</p>
        </div>
        <Button icon={ChevronRight} aria-label="Следующий слайд" disabled={selectedSlide >= total} onClick={() => setSelectedSlide(selectedSlide + 1)} className="rounded-full" />
      </div>

      <DesignNote key={`d${selectedSlide}/${v.strategy}`} v={v} index={selectedSlide} />

      <section key={`${selectedSlide}/${rev}`} className="animate-fade-in rounded-3xl bg-white p-6 shadow-card">
        <h3 className="text-[17px] font-semibold text-zinc-900">Как собран слайд</h3>
        <div className="mt-4 flex items-center gap-4">
          {pattern ? (
            <Frame src={pattern.thumbnail_url ?? null} label={`Образец: слайд ${pattern.source_slide} шаблона`} aspect={aspect} muted />
          ) : nearest ? (
            <Frame src={nearest.thumbnail_url ?? null} label={`Ближайший образец: слайд ${nearest.source_slide} шаблона`} aspect={aspect} muted />
          ) : (
            <Frame src={null} label="Слайд собран из цветов, шрифтов и сетки шаблона" aspect={aspect} />
          )}
          <ArrowRight className="h-5 w-5 shrink-0 text-zinc-400" aria-hidden />
          <Frame src={own} label="Ваш слайд" aspect={aspect} />
        </div>
        {composed && (
          <p className="mt-5 text-[13px] leading-5 text-zinc-600">
            Раскладка рассчитана под ваш текст: сетка, шкала шрифтов, цвета и карточки взяты из шаблона, а размеры блоков подобраны под объём содержания.
          </p>
        )}
        {match !== null && !composed && (
          <div className="mt-5">
            <div className="flex items-baseline justify-between text-[13px]">
              <span className="font-medium text-zinc-700">Оценка подбора</span>
              <span className="font-semibold tabular-nums text-zinc-900">{match}/100</span>
            </div>
            <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-zinc-100">
              <div className={cn("h-full rounded-full transition-[width] duration-700 ease-out", !pattern ? "bg-zinc-400" : match >= 70 ? "bg-emerald-500" : "bg-accent")} style={{ width: `${match}%` }} />
            </div>
            <p className="mt-1.5 text-xs text-zinc-500">
              {!pattern
                ? "Ни один образец не подошёл достаточно хорошо — слайд собран с нуля в стиле шаблона"
                : runnerUp === null
                  ? "Единственный макет шаблона, подходящий для такого слайда"
                  : runnerUp <= match
                    ? `Лучший из рассмотренных: у остальных макетов ${runnerUp}/100 и ниже`
                    : entry?.reasons.some((r) => r.startsWith("автофикс:"))
                      ? `Заменён проверкой качества: макет с оценкой ${runnerUp}/100 дал замечания`
                      : "Выбран с учётом стиля варианта и соседних слайдов"}
            </p>
          </div>
        )}
        {reasons.length > 0 && (
          <ul className="mt-5 space-y-2">
            {reasons.map((r) => (
              <li key={r.text} className="flex items-start gap-2.5 text-[14px] leading-5 text-zinc-800">
                <span className={cn("mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full", r.good ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700")} aria-hidden>
                  {r.good ? <Check className="h-3 w-3" strokeWidth={3} /> : <Minus className="h-3 w-3" strokeWidth={3} />}
                </span>
                {r.text}
              </li>
            ))}
          </ul>
        )}
        {!entry && <p className="mt-4 text-[13px] text-zinc-500">Для этого слайда нет записи в плане раскладки.</p>}
      </section>

      {alternatives.length > 0 && (
        <section className="rounded-3xl bg-white p-6 shadow-card">
          <h3 className="text-[17px] font-semibold text-zinc-900">{composed ? "Похожие образцы шаблона" : "Другие подходящие макеты"}</h3>
          <p className="mt-0.5 text-[13px] text-zinc-500">{composed ? "Их стиль тоже учтён: заголовки, карточки, цвета" : "Их тоже рассматривали для этого слайда"}</p>
          <div className="mt-4 grid grid-cols-3 gap-4">
            {alternatives.map(({ p, score }) => (
              <figure key={p.id} className="min-w-0">
                <div className="overflow-hidden rounded-xl bg-zinc-100 shadow-inner-line" style={{ aspectRatio: String(aspect) }}>
                  {p.thumbnail_url && <img src={p.thumbnail_url} alt="" loading="lazy" draggable={false} className="h-full w-full object-cover" />}
                </div>
                <figcaption className="mt-1.5 flex items-baseline justify-between gap-2 text-xs">
                  <span className="truncate text-zinc-600">Слайд {p.source_slide} · {kindLabel(p.kind)}</span>
                  <span className="shrink-0 font-semibold tabular-nums text-zinc-900">{Math.round(score * 100)}/100</span>
                </figcaption>
              </figure>
            ))}
          </div>
        </section>
      )}

      <section className="overflow-hidden rounded-3xl bg-white shadow-card">
        <h3 className="px-6 pb-2 pt-5 text-[17px] font-semibold text-zinc-900">Проверка качества этого слайда</h3>
        {!v.audit ? (
          <p className="px-6 pb-5 text-[13px] text-zinc-500">Проверка для этого варианта не запускалась.</p>
        ) : issues.length === 0 ? (
          <p className="flex items-center gap-2 px-6 pb-5 text-[14px] text-emerald-700">
            <Check className="h-4 w-4" strokeWidth={3} aria-hidden /> Замечаний нет
          </p>
        ) : (
          <ul className="divide-y divide-zinc-100 pb-1">{issues.map((i) => <IssueLine key={i.id} issue={i} />)}</ul>
        )}
      </section>

      {entry && <Trace entry={entry} />}
    </div>
  );
}
