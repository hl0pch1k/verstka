// Dev only (/?replay=<generation id>[&speed=3]): a finished build played again on the build screen — the agent's
// recorded events at their own pace (sped up), then the pipeline's layout, export and check messages — folded by the
// same foldJobEvent as a live build. For working on the stage without spending model requests. Never in the production
// bundle: main.tsx imports it only under import.meta.env.DEV.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { BuildScreen } from "../components/BuildScreen";
import { Header } from "../components/shell/Header";
import { foldJobEvent, type ActiveJob } from "../lib/jobState";
import { useApp } from "../store";
import type { AgentEvent, Generation, JobEvent } from "../types";

interface Step { at: number; ev: JobEvent }

function script(g: Generation, speed: number): Step[] {
  const names = g.variants.map((v) => v.strategy);
  // the first variant's record has the shared steps and its own; the others add their own
  const events: AgentEvent[] = [...(g.variants[0]?.agent?.events ?? [])];
  for (const v of g.variants.slice(1)) for (const e of v.agent?.events ?? []) if (e.variant === v.strategy) events.push(e);
  events.sort((a, b) => (a.t ?? 0) - (b.t ?? 0));
  const steps: Step[] = [];
  let at = 0;
  const push = (gap: number, ev: Partial<JobEvent> & { progress: number; message: string }) => {
    at += gap;
    steps.push({ at, ev: { job_id: "replay", status: "running", t: at / 1000, ...ev } });
  };
  push(400, { progress: 0.03, message: "analyze: loaded cached manifest" });
  push(500, { progress: 0.15, message: `plan: ${names.length} variants` });
  let prev = events[0]?.t ?? 0;
  events.forEach((e, i) => {
    const t = e.t ?? prev;
    push(Math.min(1400, Math.max(70, ((t - prev) * 1000) / speed)), { type: "agent", step: e.step, message: e.message, slide: e.slide, variant: e.variant, seq: i + 1, fix: e.fix ?? null, progress: 0.15 + 0.45 * ((i + 1) / Math.max(1, events.length)), t });
    prev = t;
  });
  g.variants.forEach((v, vi) => {
    const n = v.slides.length || v.outline?.slides.length || 10;
    const base = 0.6 + (0.25 * vi) / names.length;
    const span = 0.25 / names.length;
    push(400, { progress: base, message: `${v.strategy}: planned ${n} slides, rendering` });
    for (let k = 1; k <= n; k++) push(140, { progress: base + span * (k / n), message: `${v.strategy}: rendered slide ${k}/${n}` });
  });
  push(800, { progress: 0.86, message: "export: pdf, html, slide previews" });
  names.forEach((name) => push(900, { progress: 0.9, message: `${name}: audit` }));
  names.forEach((name) => push(600, { progress: 0.97, message: `${name}: done in 42.0s` }));
  return steps;
}

export default function StageReplay({ gid, speed }: { gid: string; speed: number }) {
  const { strategyTitle } = useApp();
  const titleOf = useRef(strategyTitle);
  titleOf.current = strategyTitle;
  const [job, setJob] = useState<ActiveJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const timers: number[] = [];
    api.generation(gid).then(
      (g) => {
        if (!alive) return;
        let cur: ActiveJob = {
          id: "replay", label: "Повтор сборки", progress: 0, message: "В очереди…", status: "queued", kind: "generate", startedAt: Date.now(),
          items: g.variants.map((v) => v.strategy), template: g.template_id, generation: g.id, slides: g.slides ?? null,
        };
        setJob(cur);
        for (const s of script(g, speed)) {
          timers.push(window.setTimeout(() => {
            cur = foldJobEvent(cur, s.ev, (n) => titleOf.current(n));
            setJob(cur);
          }, s.at));
        }
      },
      (e) => alive && setError(String(e)),
    );
    return () => {
      alive = false;
      timers.forEach((t) => window.clearTimeout(t));
    };
  }, [gid, speed]);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <Header />
      <main data-follow className="scroll-thin relative min-w-0 flex-1 overflow-y-auto">
        {job ? <BuildScreen job={job} /> : <p className="p-8 text-body text-zinc-500">{error ?? "Загружаю сборку…"}</p>}
      </main>
    </div>
  );
}
