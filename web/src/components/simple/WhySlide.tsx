// «Почему слайд такой»: the sample of the template next to the slide made from it, how well it matched, the reasons
// in words, other layouts that also fit, and the remarks of the quality check. The raw trace stays folded below.
import { useState } from "react";
import { ArrowRight, Check, ChevronLeft, ChevronRight, Minus } from "lucide-react";
import { slideCount } from "../../lib/narrate";
import { humanReasons } from "../../lib/reasons";
import { cn, kindLabel } from "../../lib/utils";
import { useApp } from "../../store";
import type { LayoutSlide, Pattern } from "../../types";
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
    .filter((a): a is { p: Pattern; score: number } => !!a.p && a.score > 0.05 && a.p.id !== pattern?.id)
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

      <section key={`${selectedSlide}/${rev}`} className="animate-fade-in rounded-3xl bg-white p-6 shadow-card">
        <h3 className="text-[17px] font-semibold text-zinc-900">Как собран слайд</h3>
        <div className="mt-4 flex items-center gap-4">
          {pattern ? (
            <Frame src={pattern.thumbnail_url ?? null} label={`Образец: слайд ${pattern.source_slide} шаблона`} aspect={aspect} muted />
          ) : (
            <Frame src={null} label="Подходящего образца нет — слайд собран из цветов, шрифтов и сетки шаблона" aspect={aspect} />
          )}
          <ArrowRight className="h-5 w-5 shrink-0 text-zinc-400" aria-hidden />
          <Frame src={own} label="Ваш слайд" aspect={aspect} />
        </div>
        {match !== null && (
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
          <h3 className="text-[17px] font-semibold text-zinc-900">Другие подходящие макеты</h3>
          <p className="mt-0.5 text-[13px] text-zinc-500">Их тоже рассматривали для этого слайда</p>
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
