// «Макеты слайдов» of the template: every sample slide the analyser can reuse, filtered by type; a click opens the
// slot map and how the type was decided.
import { useMemo, useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { cn, kindLabel, plural } from "../lib/utils";
import type { Pattern, PatternKind, TemplateManifest } from "../types";
import { PatternModal } from "./TemplatePanelPatternModal";
import { PatternThumb } from "./TemplatePanelShared";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";

function PatternCard({ pattern, aspect, onOpen }: { pattern: Pattern; aspect: string; onOpen: () => void }) {
  return (
    <button type="button" onClick={onOpen} title="Открыть разметку слайда" className="group block cursor-pointer text-left focus:outline-none">
      <span className="relative block overflow-hidden rounded-xl bg-zinc-100 shadow-inner-line transition-shadow duration-200 group-hover:shadow-raise group-focus-visible:shadow-[0_0_0_2px_#0077FF]" style={{ aspectRatio: aspect }}>
        <PatternThumb src={pattern.thumbnail_url} alt={`Слайд ${pattern.source_slide}: ${kindLabel(pattern.kind)}`} className="transition-transform duration-300 group-hover:scale-[1.03]" />
      </span>
      <span className="mt-2 flex items-baseline justify-between gap-2 px-0.5 text-[13px]">
        <span className="truncate font-medium text-zinc-900">{kindLabel(pattern.kind)}</span>
        <span className="shrink-0 text-xs tabular-nums text-zinc-400">слайд {pattern.source_slide}</span>
      </span>
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

  const activeKind = kind !== "all" && kinds.some(([k]) => k === kind) ? kind : "all";
  const shown = activeKind === "all" ? patterns : patterns.filter((p) => p.kind === activeKind);
  const openIndex = shown.findIndex((p) => p.id === openId);
  if (patterns.length === 0) return null;

  const chip = (active: boolean, label: string, count: number, onClick: () => void) => (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full px-3 text-[13px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30",
        active ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200/70",
      )}
    >
      {label}
      <span className={cn("text-xs tabular-nums", active ? "text-white/60" : "text-zinc-400")}>{count}</span>
    </button>
  );

  return (
    <Card>
      <CardHeader
        actions={
          <a href={manifest.gallery_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[13px] font-semibold text-accent-700 hover:underline">
            Все на одной странице <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
          </a>
        }
      >
        <CardTitle hint={`${plural(patterns.length, "образец", "образца", "образцов")}, по которым Verstka собирает слайды`}>Макеты слайдов</CardTitle>
      </CardHeader>
      <CardBody className="space-y-5">
        <div className="flex flex-wrap gap-1.5">
          {chip(activeKind === "all", "Все", patterns.length, () => setKind("all"))}
          {kinds.map(([k, n]) => (
            <span key={k}>{chip(activeKind === k, kindLabel(k), n, () => setKind(k))}</span>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-x-4 gap-y-5">
          {shown.map((p) => <PatternCard key={p.id} pattern={p} aspect={aspect} onOpen={() => setOpenId(p.id)} />)}
        </div>
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
