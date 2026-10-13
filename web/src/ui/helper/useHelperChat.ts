// Переписка с помощником: отправка вопроса (`api.chat` с открытой презентацией, вариантом и слайдом), ответ в ленту и
// действия ответа — их ведёт эта же плита, она смонтирована всегда (закрытая лишь скрыта), поэтому продолжения задач
// доходят до ленты и тогда, когда помощник закрыт. Логика действий — как до «Слоёв», переписанная под них;
// что делает ответ — чистая planActions (chat.ts): действия — только для презентации, о которой ответ.
//  · generation_started — экран «Сборка» с этой сборкой (followDeck по её мете, как из «Мои презентации»; мета не
//    прочиталась — по задаче из ответа: идущую сборку не открываем как готовую; мета читается ещё раз, когда список
//    обновился, и дополняет запрос сборки — adoptBuildMeta);
//  · edit (правка слайда, изображение) и jobs («Исправь всё») — задачи хранилища (`runJob`) с целью-вариантом: кнопки
//    работы над ним выключены, пока задача идёт; ход каждой — своя полоса в ленте (`liveJobs`); готово — презентация
//    перечитывается, если она открыта (`reloadIfOpen`; сцена сменяет слайд перекрёстным затуханием), открыта другая —
//    тихая строка «Это другая презентация…», не перечиталась — причина по-русски;
//  · open_tab — лист «Подробнее» на нужной вкладке (openTabSteps), если открыта та презентация, о которой ответ.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { sessionId } from "../../lib/utils";
import { useApp } from "../../store";
import type { ChatResponse, Generation, Job } from "../../types";
import {
  asEditResult, asFixResult, chatFailText, chatTarget, describeFixes, editFailText, feedProgress, planActions, reloadFailText, OTHER_DECK,
  type EditAction, type Edited, type FeedJob, type FeedNote, type FixOutcome,
} from "./chat";

export interface HelperChat {
  jobs: FeedJob[];
  /** Тихие строки ленты («Это другая презентация…»). */
  notes: FeedNote[];
  /** Ответ ещё не пришёл. */
  pending: boolean;
  /** Последняя правка изменила презентацию `gid`, открытую тогда (подсказки «Верни как было» и «Почему слайд N
   *  такой?» — только пока она на экране, chipsFor); null — нет. */
  edited: Edited | null;
  /** Идёт задача, начатая из чата. */
  working: boolean;
  /** Отправить вопрос; false — не ушёл (пусто или ответ ещё не пришёл). */
  send(text: string): boolean;
}

/** Чем кончилось перечитывание после правки: презентация на экране обновилась; открыта другая; не перечиталась. */
type Reload = { kind: "open"; g: Generation } | { kind: "other" } | { kind: "failed"; error: unknown };

const now = () => Date.now() / 1000;

export function useHelperChat(): HelperChat {
  const app = useApp();
  // продолжения задач приходят через минуты: всегда читаем свежее состояние
  const latest = useRef(app);
  latest.current = app;
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const [jobs, setJobs] = useState<FeedJob[]>([]);
  const [notes, setNotes] = useState<FeedNote[]>([]);
  const [edited, setEdited] = useState<Edited | null>(null);
  /** Сборка из чата, чья мета не прочиталась (followNewBuild): её мета читается ещё раз, когда обновится список. */
  const lateMeta = useRef<string | null>(null);

  const addJob = useCallback((id: string, label: string) => {
    setJobs((js) => (js.some((j) => j.id === id) ? js : [...js, { id, label, ts: now(), progress: 0, status: "run" }]));
  }, []);
  const settleJob = useCallback((id: string, status: "done" | "failed") => {
    setJobs((js) => js.map((j) => (j.id === id ? { ...j, status, progress: status === "done" ? 1 : j.progress } : j)));
  }, []);
  const addNote = useCallback((text: string) => {
    setNotes((ns) => [...ns, { id: `n${Date.now()}-${ns.length}`, text, ts: now() }]);
  }, []);
  // ход задач — по идущим задачам хранилища: у каждой полосы своя задача («Исправь всё» — по задаче на вариант)
  const live = app.liveJobs;
  useEffect(() => {
    setJobs((js) => feedProgress(js, live));
  }, [live]);

  /** Перечитать презентацию `gid` после изменения: она открыта — обновляется на экране; открыта другая — сказать об этом;
   *  не перечиталась (связь, сервер) — причина, а не «другая презентация». */
  const reloadDeck = useCallback(async (gid: string): Promise<Reload> => {
    if (latest.current.generation?.id !== gid) return { kind: "other" };
    let failed = false;
    let error: unknown = null;
    const g = await latest.current.reloadIfOpen(gid, (e) => {
      failed = true;
      error = e;
    });
    if (g) return { kind: "open", g };
    return failed ? { kind: "failed", error } : { kind: "other" };
  }, []);
  /** Что сказать в ленте после перечитывания: открыта другая — тихая строка; не перечиталась — причина. */
  const tellReload = useCallback((r: Reload | null) => {
    if (r?.kind === "other") addNote(OTHER_DECK);
    else if (r?.kind === "failed") latest.current.pushMessage("assistant", reloadFailText(r.error));
  }, [addNote]);

  const followEdit = useCallback((a: EditAction) => {
    const s = latest.current;
    const gid = a.generation_id;
    addJob(a.job_id, "Меняю презентацию");
    s.runJob(a.job_id, "Меняю презентацию", {
      kind: "edit", area: "result", quiet: true, generation: gid, target: { generation: gid, strategy: a.strategy, slide: a.slide ?? 0 },
      onDone: async (job: Job) => {
        const r = asEditResult(job.result);
        settleJob(a.job_id, "done");
        let after: Reload | null = null;
        if (r?.changed) {
          void latest.current.refreshGenerations();
          after = await reloadDeck(gid);
          // «Верни как было» и вопрос о слайде — только когда на экране та презентация, которую изменили
          if (after.kind === "open") {
            setEdited(r.kind === "undo" ? null : { gid, slide: r.slide ?? a.slide ?? null });
            const strategy = r.strategy ?? a.strategy;
            if (strategy && latest.current.activeStrategy !== strategy) latest.current.setActiveStrategy(strategy);
            if (r.slide) latest.current.setSelectedSlide(r.slide);
          }
        }
        latest.current.pushMessage("assistant", r?.reply ?? "Готово.");
        tellReload(after);
      },
      onFailed: (job: Job) => {
        settleJob(a.job_id, "failed");
        latest.current.pushMessage("assistant", editFailText(job.error ?? job.message));
      },
    });
  }, [addJob, settleJob, reloadDeck, tellReload]);

  const followFixes = useCallback((list: { strategy: string; job_id: string }[], gid: string | null) => {
    if (!list.length) return;
    const s = latest.current;
    const open = s.generation && s.generation.id === gid ? s.generation : null;
    const before = (strategy: string) => open?.variants.find((v) => v.strategy === strategy)?.audit?.summary.score ?? null;
    const outcomes: FixOutcome[] = list.map((j) => ({ strategy: j.strategy, before: before(j.strategy), done: false, result: null, error: null }));
    let left = list.length;
    const settle = async () => {
      left -= 1;
      if (left > 0) return;
      let after: Reload | null = null;
      if (gid && outcomes.some((o) => o.done)) {
        void latest.current.refreshGenerations();
        after = await reloadDeck(gid);
      }
      latest.current.pushMessage("assistant", describeFixes(outcomes, latest.current.strategyTitle));
      tellReload(after);
    };
    list.forEach((j, i) => {
      const label = `Исправляю: ${s.strategyTitle(j.strategy)}`;
      addJob(j.job_id, label);
      s.runJob(j.job_id, label, {
        kind: "fix", area: "result", quiet: true, generation: gid, target: gid ? { generation: gid, strategy: j.strategy, slide: 0 } : undefined,
        onDone: (job: Job) => {
          settleJob(j.job_id, "done");
          outcomes[i].done = true;
          outcomes[i].result = asFixResult(job.result);
          void settle();
        },
        onFailed: (job: Job) => {
          settleJob(j.job_id, "failed");
          outcomes[i].error = job.error ?? job.message;
          void settle();
        },
      });
    });
  }, [addJob, settleJob, reloadDeck, tellReload]);

  const followNewBuild = useCallback(async (gid: string, job: string, template: string | null) => {
    // мета новой сборки уже есть (сервер пишет её до старта задачи): экран «Сборка» ведёт её, как из «Мои презентации»
    const meta = await api.generation(gid).catch(() => null);
    const s = latest.current;
    // не прочиталась — её прочитают ещё раз, когда список обновится (эффект ниже)
    lateMeta.current = meta ? null : gid;
    void s.refreshGenerations();
    // кончилась мгновенно — открытие само скажет, что вышло
    if (meta && meta.status !== "running") return void s.loadGeneration(gid);
    // идёт — или мета не прочиталась (связь): сборку ведёт её задача из ответа; идущую не открываем как готовую
    s.followDeck(meta ? { ...meta, job_id: meta.job_id ?? job } : { id: gid, template_id: template ?? s.templateId ?? "", strategies: [], status: "running", job_id: job });
  }, []);
  // мета сборки из чата не прочиталась: список обновился и в нём есть эта сборка (связь вернулась) — мета читается ещё
  // раз, и полоса 02 и «Собрать ещё раз» берут из неё тему и варианты вместо заглушки (adoptBuildMeta — только если на
  // экране всё ещё запрос-заглушка этой сборки). Не прочиталась и теперь — ещё раз при следующем обновлении списка
  const listed = app.generations;
  useEffect(() => {
    const gid = lateMeta.current;
    if (!gid || !listed.some((g) => g.id === gid)) return;
    void api.generation(gid).then((g) => {
      if (lateMeta.current !== gid) return;
      lateMeta.current = null;
      latest.current.adoptBuildMeta(g);
    }, () => {});
  }, [listed]);

  const perform = useCallback((res: ChatResponse, sent: string | null) => {
    const s = latest.current;
    const plan = planActions(res, { sent, open: s.generation?.id ?? null, screen: s.ui.screen, hasDeck: !!s.generation?.variants.length });
    for (const p of plan) {
      if (p.kind === "build") void followNewBuild(p.gid, p.job, res.template_id);
      else if (p.kind === "edit") followEdit(p.action);
      else if (p.kind === "fixes") followFixes(p.jobs, p.gid);
      else {
        if (p.slide) latest.current.setSelectedSlide(p.slide);
        for (const step of p.steps) latest.current.dispatch(step);
      }
    }
  }, [followNewBuild, followEdit, followFixes]);

  const send = useCallback((raw: string) => {
    const message = raw.trim();
    if (!message || busy.current) return false;
    busy.current = true;
    setPending(true);
    setEdited(null);
    const s = latest.current;
    s.pushMessage("user", message);
    // вопрос — о том, что на экране: на результате — открытая презентация, её вариант и слайд («почему слайд 3 такой» —
    // про него), на «Сборке» — собираемая, на «Создать» — никакая; ответ действует только на неё (planActions), даже
    // если пока ждали, открыли другую
    const target = chatTarget({
      screen: s.ui.screen, open: s.generationId, strategy: s.activeStrategy, slide: s.generation ? s.selectedSlide : null,
      building: s.buildJob?.generation ?? null,
    });
    const sent = target.generation_id;
    void api.chat({ session_id: sessionId(), message, template_id: s.templateId, ...target }).then((res) => {
      latest.current.pushMessage("assistant", res.reply);
      perform(res, res.generation_id ?? sent);
    }, (e: unknown) => {
      latest.current.pushMessage("assistant", chatFailText(e));
    }).finally(() => {
      busy.current = false;
      setPending(false);
    });
    return true;
  }, [perform]);

  const working = jobs.some((j) => j.status === "run");
  return { jobs, notes, pending, edited, working, send };
}
