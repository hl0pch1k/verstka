// «Макеты» of the template: six sample slides at first, all of them (filtered by type) on «Все N»; a click opens the
// slot map and how the type was decided. Motion: the first six fade up in a 40 ms cascade when the tab opens, «Все N»
// cascades the ones it reveals, a type chip cross-fades the grid, and a hovered sample zooms in slightly.
import { useMemo, useRef, useState, type CSSProperties } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { stagger } from "../lib/motion";
import { cn, kindLabel } from "../lib/utils";
import type { Pattern, PatternKind, TemplateManifest } from "../types";
import { PatternModal } from "./TemplatePanelPatternModal";
import { PatternThumb } from "./TemplatePanelShared";
import { Button } from "./ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";
import { Chip } from "./ui/Chip";

const FIRST = 6; // two rows of three

function PatternCard({ pattern, aspect, onOpen, className, style }: { pattern: Pattern; aspect: string; onOpen: () => void; className?: string; style?: CSSProperties }) {
  const kind = kindLabel(pattern.kind);
  return (
    <button type="button" onClick={onOpen} aria-label={`Слайд ${pattern.source_slide}: ${kind}`} className={cn("tap-soft group block min-w-0 cursor-pointer rounded-lg text-left", className)} style={style}>
      {/* the hairline edge is drawn over the picture: a white slide keeps its border on the white card */}
      <span className="relative block overflow-hidden rounded-lg bg-zinc-100 transition-shadow duration-150 group-hover:shadow-raise after:pointer-events-none after:absolute after:inset-0 after:rounded-lg after:shadow-inner-line after:content-['']" style={{ aspectRatio: aspect }}>
        <PatternThumb src={pattern.thumbnail_url} alt="" className="transition-transform duration-300 ease-out group-hover:scale-[1.03]" />
      </span>
      <span className="mt-2 flex items-baseline justify-between gap-2">
        <span className="truncate text-footnote font-semibold text-zinc-900" title={kind}>{kind}</span>
        <span className="shrink-0 text-caption tabular-nums text-zinc-500">слайд {pattern.source_slide}</span>
      </span>
    </button>
  );
}

/** How long an entrance class stays on (past the longest cascade: 6 × 40 + 200 ms). */
const ENTER_MS = 800;

export function PatternGallery({ manifest }: { manifest: TemplateManifest }) {
  const [kind, setKindState] = useState<PatternKind | "all">("all");
  const [all, setAll] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  // the first samples cascade in when the tab opens; «Все N» cascades the ones it reveals; a type chip cross-fades
  const mountedAt = useRef(performance.now());
  const [revealAt, setRevealAt] = useState(-Infinity);
  const picked = useRef(false);
  const setKind = (k: PatternKind | "all") => {
    picked.current = true;
    setKindState(k);
  };
  const { patterns, slide_size: size } = manifest;
  const aspect = size.w && size.h ? `${size.w} / ${size.h}` : "16 / 9";

  // the kinds by count (a kind with one sample comes late); «Другое» is the catch-all and always goes last
  const kinds = useMemo(() => {
    const counts = new Map<PatternKind, number>();
    patterns.forEach((p) => counts.set(p.kind, (counts.get(p.kind) ?? 0) + 1));
    const last = (k: PatternKind) => (k === "freeform" ? 1 : 0);
    return [...counts.entries()].sort((a, b) => last(a[0]) - last(b[0]) || b[1] - a[1] || kindLabel(a[0]).localeCompare(kindLabel(b[0]), "ru"));
  }, [patterns]);

  const activeKind = all && kind !== "all" && kinds.some(([k]) => k === kind) ? kind : "all";
  const pool = activeKind === "all" ? patterns : patterns.filter((p) => p.kind === activeKind);
  const shown = all ? pool : pool.slice(0, FIRST);
  const openIndex = pool.findIndex((p) => p.id === openId);
  if (patterns.length === 0) return null;

  const toggle = () => {
    if (!all) setRevealAt(performance.now());
    setAll(!all);
    setKindState("all");
  };
  const now = performance.now();
  const tile = (i: number): { className?: string; style?: CSSProperties } =>
    now - mountedAt.current < ENTER_MS && i < FIRST
      ? { className: "animate-fade-in", style: stagger(i) }
      : now - revealAt < ENTER_MS && i >= FIRST
        ? { className: "animate-fade-in", style: stagger(i - FIRST) }
        : {};

  return (
    <Card>
      <CardHeader
        actions={
          patterns.length > FIRST && (
            <Button size="sm" variant="ghost" iconRight={all ? ChevronUp : ChevronDown} aria-expanded={all} onClick={toggle} className="-mr-3">
              {all ? "Свернуть" : `Все ${patterns.length}`}
            </Button>
          )
        }
      >
        <CardTitle count={patterns.length}>Макеты</CardTitle>
      </CardHeader>
      <CardBody className="space-y-4">
        {/* every kind in view: the chips wrap (two rows at most) instead of hiding the rarer kinds behind a scroll */}
        {all && kinds.length > 1 && (
          <div className="flex flex-wrap gap-2 animate-fade" role="group" aria-label="Тип слайда">
            <Chip selected={activeKind === "all"} aria-pressed={activeKind === "all"} count={patterns.length} onClick={() => setKind("all")}>
              Все
            </Chip>
            {kinds.map(([k, n]) => (
              <Chip key={k} selected={activeKind === k} aria-pressed={activeKind === k} count={n} onClick={() => setKind(k)}>
                {kindLabel(k)}
              </Chip>
            ))}
          </div>
        )}
        <div key={activeKind} className={cn("grid grid-cols-3 gap-x-3 gap-y-4", picked.current && "animate-fade")}>
          {shown.map((p, i) => <PatternCard key={p.id} pattern={p} aspect={aspect} onOpen={() => setOpenId(p.id)} {...tile(i)} />)}
        </div>
      </CardBody>
      <PatternModal
        pattern={openIndex >= 0 ? pool[openIndex] : null}
        aspect={aspect}
        position={openIndex >= 0 ? `${openIndex + 1} / ${pool.length}` : ""}
        onClose={() => setOpenId(null)}
        onStep={(delta) => {
          if (openIndex < 0) return;
          setOpenId(pool[(openIndex + delta + pool.length) % pool.length].id);
        }}
      />
    </Card>
  );
}
