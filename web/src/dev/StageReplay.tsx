// Dev only (/?replay=<generation id>[&speed=3][&fail=critic][&pause=5000]): a finished build played again on the «Сборка» plate —
// the agent's recorded events at their own pace (sped up), the pipeline's layout, check and export messages around
// them — folded by the same foldJobEvent as a live build, shown by the same BuildPlate inside the whole deck. At the end
// the deck opens on the result, as after a real build. `fail=<phase>`: the build stops 1.3 s into that phase (V2
// `bdFail`) with «Модель не ответила…» — the B-failed state; «Собрать ещё раз» plays it again to the end. `pause`: the
// build stays queued that long first (the B-start state, its clock running). For working
// on the build screen without spending model requests. Never in the production bundle: main.tsx imports it only under
// import.meta.env.DEV.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { phaseOfStep, type PhaseKey } from "../lib/agent";
import { eyesSkipEvent } from "../lib/designEye";
import { foldJobEvent, type ActiveJob } from "../lib/jobState";
import { useApp } from "../store";
import type { AgentEvent, Generation, JobEvent } from "../types";
import { BuildReplay } from "../ui/build/BuildPlate";
import { AppShell } from "../ui/shell/AppShell";

interface Step { at: number; ev: JobEvent }

const FAIL_TEXT = "Модель не ответила: сервер модели перегружен";

function script(g: Generation, speed: number): Step[] {
  const names = g.variants.map((v) => v.strategy);
  // the first variant's record has the shared steps and its own; the others add their own
  const events: AgentEvent[] = [...(g.variants[0]?.agent?.events ?? [])];
  for (const v of g.variants.slice(1)) for (const e of v.agent?.events ?? []) if (e.variant === v.strategy) events.push(e);
  events.sort((a, b) => (a.t ?? 0) - (b.t ?? 0));
  // the vision model looks at laid out slides: its lines (and what came after them) follow the layout
  const cut = events.findIndex((e) => (e.step ?? "").toLowerCase() === "eyes");
  const planning = cut >= 0 ? events.slice(0, cut) : events;
  const after = cut >= 0 ? events.slice(cut) : [];
  const steps: Step[] = [];
  let at = 0;
  let seq = 0;
  const push = (gap: number, ev: Partial<JobEvent> & { progress: number; message: string }) => {
    at += gap;
    steps.push({ at, ev: { job_id: "replay", status: "running", t: at / 1000, ...ev } });
  };
  const agentStep = (e: AgentEvent, prev: number, progress: number) =>
    push(Math.min(1400, Math.max(70, (((e.t ?? prev) - prev) * 1000) / speed)), { type: "agent", step: e.step, message: e.message, slide: e.slide, variant: e.variant, seq: ++seq, fix: e.fix ?? null, progress, t: e.t });
  push(400, { progress: 0.03, message: "analyze: loaded cached manifest" });
  push(500, { progress: 0.15, message: `plan: ${names.length} variants` });
  let prev = planning[0]?.t ?? 0;
  planning.forEach((e, i) => {
    agentStep(e, prev, 0.15 + 0.45 * ((i + 1) / Math.max(1, planning.length)));
    prev = e.t ?? prev;
  });
  g.variants.forEach((v, vi) => {
    const n = v.slides.length || v.outline?.slides.length || 10;
    const base = 0.6 + (0.25 * vi) / names.length;
    const span = 0.25 / names.length;
    push(400, { progress: base, message: `${v.strategy}: planned ${n} slides, rendering` });
    for (let k = 1; k <= n; k++) push(160, { progress: base + span * (k / n), message: `${v.strategy}: rendered slide ${k}/${n}` });
    push(300, { progress: base + span, message: `${v.strategy}: audit` });
  });
  // a variant the server skipped «Взгляд дизайнера» for: recordings made before the timeline said so get the line the
  // server says now («Взгляд дизайнера пропущен: не хватило времени на сборку.»), after the lines of those it looked at
  const skips = g.variants.map(eyesSkipEvent).filter((e): e is AgentEvent => e !== null);
  if (after.length || skips.length) {
    names.forEach((name) => push(300, { progress: 0.85, message: `${name}: design review` }));
    prev = after[0]?.t ?? prev;
    after.forEach((e) => {
      agentStep(e, prev, 0.85);
      prev = e.t ?? prev;
    });
    skips.forEach((e) => push(600, { type: "agent", step: e.step, message: e.message, slide: null, variant: e.variant, seq: ++seq, fix: null, progress: 0.85 }));
  }
  push(800, { progress: 0.86, message: "export: pdf, html, slide previews" });
  names.forEach((name) => push(900, { progress: 0.97, message: `${name}: done in 42.0s` }));
  return steps;
}

export default function StageReplay({ gid, speed, fail, pause = 0 }: { gid: string; speed: number; fail: PhaseKey | null; pause?: number }) {
  const { strategyTitle, dispatch, loadGeneration } = useApp();
  const titleOf = useRef(strategyTitle);
  titleOf.current = strategyTitle;
  const [job, setJob] = useState<ActiveJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState(0);
  // «Собрать ещё раз» в реплее — тот же реплей до конца, без остановки
  const failOnce = useRef(fail);

  useEffect(() => {
    dispatch({ type: "go", screen: "build" });
  }, [dispatch]);

  useEffect(() => {
    let alive = true;
    const timers: number[] = [];
    const later = (ms: number, fn: () => void) => timers.push(window.setTimeout(fn, ms));
    api.generation(gid).then(
      (g) => {
        if (!alive) return;
        let cur: ActiveJob = {
          id: `replay-${run}`, label: "Повтор сборки", progress: 0, message: "В очереди…", status: "queued", kind: "generate", startedAt: Date.now(),
          items: g.variants.map((v) => v.strategy), template: g.template_id, generation: g.id, slides: g.slides ?? null,
        };
        setJob(cur);
        const steps = script(g, speed).map((s) => ({ ...s, at: s.at + (run === 0 ? pause : 0) }));
        const stopAt = failOnce.current ? steps.findIndex((s) => s.ev.type === "agent" && phaseOfStep(s.ev.step) === failOnce.current) : -1;
        const played = stopAt >= 0 ? steps.slice(0, stopAt + 1) : steps;
        for (const s of played) {
          later(s.at, () => {
            cur = foldJobEvent(cur, s.ev, (n) => titleOf.current(n));
            setJob(cur);
          });
        }
        const end = played[played.length - 1]?.at ?? 0;
        if (stopAt >= 0) {
          failOnce.current = null;
          later(end + 1300, () => setJob({ ...cur, status: "failed", message: FAIL_TEXT, endedAt: Date.now() }));
        } else {
          later(end + 600, () => setJob({ ...cur, status: "done", progress: 1, message: "Готово", endedAt: Date.now() }));
          later(end + 1400, () => {
            void loadGeneration(g.id).then((d) => d && dispatch({ type: "go", screen: "result" }));
          });
        }
      },
      (e) => alive && setError(String(e)),
    );
    return () => {
      alive = false;
      timers.forEach((t) => window.clearTimeout(t));
    };
  }, [gid, speed, pause, run, dispatch, loadGeneration]);

  const retry = useCallback(async () => {
    setRun((n) => n + 1);
    return true;
  }, []);

  if (error) return <div className="p2-root" style={{ padding: 24 }}><p style={{ margin: 0, color: "#5A6272" }}>{error}</p></div>;
  return (
    <BuildReplay.Provider value={{ job, retry }}>
      <AppShell />
    </BuildReplay.Provider>
  );
}
