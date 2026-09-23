// Pattern gallery of the template: every analysed sample slide with its kind, slots, repeat groups and votes.
import { useMemo, useState } from "react";
import { ExternalLink, LayoutGrid, Repeat, SearchX } from "lucide-react";
import { cn, fmtPct, kindLabel, plural } from "../lib/utils";
import type { ClassificationTrace, Pattern, PatternKind, TemplateManifest } from "../types";
import { PatternModal } from "./TemplatePanelPatternModal";
import { groupSummary, PatternThumb, qualityTone, votesOf } from "./TemplatePanelShared";
import { Badge } from "./ui/Badge";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";
import { EmptyState } from "./ui/EmptyState";

function Votes({ trace }: { trace: ClassificationTrace }) {
  const votes = votesOf(trace);
  return (
    <div className="flex flex-wrap items-center gap-1">
      {votes.map(({ source, vote }) => {
        const differs = vote.kind !== trace.kind;
        return (
          <span
            key={source}
            title={vote.rationale ?? undefined}
            className={cn("inline-flex h-[18px] items-center gap-1 rounded px-1.5 text-[11px]", differs ? "bg-amber-50 text-amber-800" : "bg-zinc-100 text-zinc-600")}
          >
            {source}
            {differs && <span className="font-medium">{kindLabel(vote.kind)}</span>}
            <span className="font-medium tabular-nums text-zinc-900">{fmtPct(vote.confidence)}</span>
          </span>
        );
      })}
      {votes.length > 1 && (
        <span className={cn("inline-flex h-[18px] items-center rounded px-1.5 text-[11px] font-medium", trace.agreement >= 0.99 ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800")}>
          согласие {fmtPct(trace.agreement)}
        </span>
      )}
    </div>
  );
}

function PatternCard({ pattern, aspect, onOpen }: { pattern: Pattern; aspect: string; onOpen: () => void }) {
  const groups = pattern.repeat_groups;
  return (
    <article className="group flex flex-col overflow-hidden rounded-2xl bg-zinc-50 shadow-inner-line transition-shadow duration-200 hover:bg-white hover:shadow-raise">
      <button
        type="button"
        onClick={onOpen}
        title="Открыть разбор слайда"
        className="relative block w-full cursor-pointer overflow-hidden bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/50"
        style={{ aspectRatio: aspect }}
      >
        <PatternThumb src={pattern.thumbnail_url} alt={`Слайд ${pattern.source_slide}: ${kindLabel(pattern.kind)}`} className="transition-transform duration-300 group-hover:scale-[1.02]" />
        <span className="absolute left-2 top-2 rounded-full bg-ink/75 px-2 py-0.5 text-[11px] font-semibold text-white backdrop-blur-sm">слайд {pattern.source_slide}</span>
      </button>
      <div className="flex flex-1 flex-col gap-2 px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone="accent" size="sm">{kindLabel(pattern.kind)}</Badge>
          <Badge size="sm" solid={pattern.family === "dark"}>{pattern.family === "dark" ? "тёмный" : "светлый"}</Badge>
          <span className="ml-auto font-mono text-[11px] text-zinc-400">{pattern.id}</span>
        </div>
        <div className="space-y-0.5 text-xs leading-[18px] text-zinc-600">
          <p>
            {plural(pattern.slots.length, "слот", "слота", "слотов")}
            {pattern.decor_assets.length > 0 && <span className="text-zinc-400"> · декор {pattern.decor_assets.length}</span>}
          </p>
          {groups.slice(0, 2).map((g) => (
            <p key={g.id} className="flex items-center gap-1.5 truncate">
              <Repeat className="h-3 w-3 shrink-0 text-zinc-400" aria-hidden />
              <span className="truncate">{groupSummary(g)}</span>
            </p>
          ))}
          {groups.length > 2 && <p className="pl-[18px] text-zinc-400">ещё {plural(groups.length - 2, "группа", "группы", "групп")}</p>}
        </div>
        <div className="mt-auto flex items-center gap-2 pt-0.5" title="Качество образца: чистота структуры и пригодность для повторного использования">
          <span className="text-[11px] text-zinc-500">качество</span>
          <span className="h-1 flex-1 overflow-hidden rounded-full bg-zinc-200">
            <span className={cn("block h-full rounded-full", qualityTone(pattern.quality))} style={{ width: `${Math.round(Math.min(1, Math.max(0, pattern.quality)) * 100)}%` }} />
          </span>
          <span className="w-8 text-right text-[11px] font-medium tabular-nums text-zinc-700">{fmtPct(pattern.quality)}</span>
        </div>
        {pattern.classification && <Votes trace={pattern.classification} />}
      </div>
    </article>
  );
}

function Chip({ active, label, count, onClick }: { active: boolean; label: string; count: number; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full border px-3 text-[13px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30",
        active ? "border-transparent bg-zinc-900 text-white" : "border-transparent bg-zinc-100 text-zinc-700 hover:bg-zinc-200/70",
      )}
    >
      {label}
      <span className={cn("text-[11px] tabular-nums", active ? "text-white/80" : "text-zinc-400")}>{count}</span>
    </button>
  );
}

export function PatternGallery({ manifest }: { manifest: TemplateManifest }) {
  const [kind, setKind] = useState<PatternKind | "all">("all");
  const [openId, setOpenId] = useState<string | null>(null);
  const { patterns, slide_size: size } = manifest;
  const aspect = size.w && size.h ? `${size.w} / ${size.h}` : "16 / 9";

  const kinds = useMemo(() => {
    const counts = new Map<PatternKind, number>();
    patterns.forEach((p) => counts.set(p.kind, (counts.get(p.kind) ?? 0) + 1));
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || kindLabel(a[0]).localeCompare(kindLabel(b[0]), "ru"));
  }, [patterns]);

  // A filter left over from another template must not hide the whole gallery.
  const activeKind = kind !== "all" && kinds.some(([k]) => k === kind) ? kind : "all";
  const shown = activeKind === "all" ? patterns : patterns.filter((p) => p.kind === activeKind);
  const openIndex = shown.findIndex((p) => p.id === openId);

  return (
    <Card>
      <CardHeader
        actions={
          <a
            href={manifest.gallery_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-9 items-center gap-1.5 rounded-[10px] bg-zinc-100 px-3 text-[13px] font-semibold text-zinc-900 transition-colors hover:bg-zinc-200/80 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30"
          >
            <ExternalLink className="h-3.5 w-3.5" aria-hidden /> Открыть галерею
          </a>
        }
      >
        <CardTitle icon={LayoutGrid} hint={`${plural(patterns.length, "образец", "образца", "образцов")} из ${plural(manifest.n_slides, "слайда", "слайдов", "слайдов")} · ${plural(kinds.length, "тип", "типа", "типов")} · клик по превью — слоты и голоса классификации`}>
          Паттерны слайдов
        </CardTitle>
      </CardHeader>
      <CardBody className="space-y-4">
        {patterns.length === 0 ? (
          <EmptyState compact icon={SearchX} title="Паттерны не найдены" hint="В шаблоне не нашлось слайдов, пригодных как образцы. Слайды будут собираться из дизайн-токенов." />
        ) : (
          <>
            <div className="flex flex-wrap gap-1.5">
              <Chip active={activeKind === "all"} label="Все" count={patterns.length} onClick={() => setKind("all")} />
              {kinds.map(([k, n]) => <Chip key={k} active={activeKind === k} label={kindLabel(k)} count={n} onClick={() => setKind(k)} />)}
            </div>
            <div className="grid grid-cols-3 gap-4 min-[1400px]:grid-cols-4">
              {shown.map((p) => <PatternCard key={p.id} pattern={p} aspect={aspect} onOpen={() => setOpenId(p.id)} />)}
            </div>
          </>
        )}
      </CardBody>
      <PatternModal
        pattern={openIndex >= 0 ? shown[openIndex] : null}
        aspect={aspect}
        position={openIndex >= 0 ? `${openIndex + 1} из ${shown.length}` : ""}
        onClose={() => setOpenId(null)}
        onStep={(delta) => {
          if (openIndex < 0) return;
          setOpenId(shown[(openIndex + delta + shown.length) % shown.length].id);
        }}
      />
    </Card>
  );
}
