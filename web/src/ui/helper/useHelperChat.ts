// Переписка с помощником: отправка вопроса (`api.chat` с открытой презентацией, вариантом и слайдом), ответ в ленту и
// действия ответа — их ведёт эта же плита, она смонтирована всегда (закрытая лишь скрыта), поэтому продолжения задач
// доходят до ленты и тогда, когда помощник закрыт. Логика действий — старый ChatActions.ts, переписанный под «Слои»:
//  · generation_started — экран «Сборка» с этой сборкой (followDeck по её мете, как из «Мои презентации»);
//  · edit (правка слайда, изображение) и jobs («Исправь всё») — задачи хранилища (`runJob`) с целью-вариантом: кнопки
//    работы над ним выключены, пока задача идёт; готово — открытая презентация перечитывается (`reloadIfOpen`), сцена
//    сменяет слайд перекрёстным затуханием; ход — полоса в ленте, итог и неудача — сообщением помощника;
//  · open_tab — лист «Подробнее» на нужной вкладке (openTabSteps).
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { sessionId } from "../../lib/utils";
import { useApp } from "../../store";
import type { ChatAction, ChatResponse, Job } from "../../types";
import {
  asEditResult, asFixResult, chatFailText, describeFixes, editFailText, openTabSteps, type FeedJob, type FixOutcome,
} from "./chat";

export interface HelperChat {
  jobs: FeedJob[];
  /** Ответ ещё не пришёл. */
  pending: boolean;
  /** Последняя правка изменила презентацию (подсказка «Верни как было»); null — нет. */
  edited: { slide: number | null } | null;
  /** Идёт задача, начатая из чата. */
  working: boolean;
  /** Отправить вопрос; false — не ушёл (пусто или ответ ещё не пришёл). */
  send(text: string): boolean;
}

const now = () => Date.now() / 1000;

export function useHelperChat(): HelperChat {
  const app = useApp();
  // продолжения задач приходят через минуты: всегда читаем свежее состояние
  const latest = useRef(app);
  latest.current = app;
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const [jobs, setJobs] = useState<FeedJob[]>([]);
  const [edited, setEdited] = useState<{ slide: number | null } | null>(null);

  const addJob = useCallback((id: string, label: string) => {
    setJobs((js) => (js.some((j) => j.id === id) ? js : [...js, { id, label, ts: now(), progress: 0, status: "run" }]));
  }, []);
  const settleJob = useCallback((id: string, status: "done" | "failed") => {
    setJobs((js) => js.map((j) => (j.id === id ? { ...j, status, progress: status === "done" ? 1 : j.progress } : j)));
  }, []);
  // ход задачи — по слоту хранилища (самая новая идущая задача): полоса в ленте растёт вместе с ней
  const live = app.activeJob;
  useEffect(() => {
    if (!live) return;
    setJobs((js) => (js.some((j) => j.id === live.id && j.status === "run" && j.progress !== live.progress)
      ? js.map((j) => (j.id === live.id ? { ...j, progress: Math.max(j.progress, live.progress) } : j)) : js));
  }, [live]);

  const followEdit = useCallback((a: Extract<ChatAction, { type: "edit" }>) => {
    const s = latest.current;
    const gid = a.generation_id;
    addJob(a.job_id, "Меняю презентацию");
    s.runJob(a.job_id, "Меняю презентацию", {
      kind: "edit", area: "result", quiet: true, generation: gid, target: { generation: gid, strategy: a.strategy, slide: a.slide ?? 0 },
      onDone: async (job: Job) => {
        const r = asEditResult(job.result);
        settleJob(a.job_id, "done");
        if (r?.changed) {
          // после «верни как было» подсказка себя не предлагает
          setEdited(r.kind === "undo" ? null : { slide: r.slide ?? a.slide ?? null });
          void latest.current.refreshGenerations();
          const g = await latest.current.reloadIfOpen(gid);
          if (g) {
            const strategy = r.strategy ?? a.strategy;
            if (strategy && latest.current.activeStrategy !== strategy) latest.current.setActiveStrategy(strategy);
            if (r.slide) latest.current.setSelectedSlide(r.slide);
          }
        }
        latest.current.pushMessage("assistant", r?.reply ?? "Готово.");
      },
      onFailed: (job: Job) => {
        settleJob(a.job_id, "failed");
        latest.current.pushMessage("assistant", editFailText(job.error ?? job.message));
      },
    });
  }, [addJob, settleJob]);

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
      let elsewhere = false;
      if (gid && outcomes.some((o) => o.done)) {
        void latest.current.refreshGenerations();
        elsewhere = !(await latest.current.reloadIfOpen(gid));
      }
      const text = describeFixes(outcomes, latest.current.strategyTitle);
      latest.current.pushMessage("assistant", elsewhere ? `${text}\nЭто другая презентация — она в «Мои презентации».` : text);
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
  }, [addJob, settleJob]);

  const followNewBuild = useCallback(async (gid: string) => {
    // мета новой сборки уже есть (сервер пишет её до старта задачи): экран «Сборка» ведёт её, как из «Мои презентации»
    const meta = await api.generation(gid).catch(() => null);
    const s = latest.current;
    void s.refreshGenerations();
    if (meta?.status === "running" && meta.job_id) s.followDeck(meta);
    else void s.loadGeneration(gid); // кончилась мгновенно или мета не прочиталась: открытие само скажет, что вышло
  }, []);

  const perform = useCallback((res: ChatResponse) => {
    for (const a of res.actions ?? []) {
      if (a.type === "generation_started") void followNewBuild(a.generation_id);
      else if (a.type === "edit") followEdit(a);
      else if (a.type === "jobs") followFixes(a.jobs ?? [], res.generation_id ?? latest.current.generationId);
      else if (a.type === "open_tab") {
        const s = latest.current;
        const hasDeck = !!s.generation?.variants.length;
        if (a.slide && hasDeck) s.setSelectedSlide(a.slide);
        for (const step of openTabSteps(a.tab, { screen: s.ui.screen, hasDeck })) s.dispatch(step);
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
    // вопрос — о том, что на экране: открытая презентация, её вариант и слайд («почему слайд 3 такой» — про него)
    void api.chat({
      session_id: sessionId(), message, template_id: s.templateId, generation_id: s.generationId, strategy: s.activeStrategy,
      slide: s.generation ? s.selectedSlide : null,
    }).then((res) => {
      latest.current.pushMessage("assistant", res.reply);
      perform(res);
    }, (e: unknown) => {
      latest.current.pushMessage("assistant", chatFailText(e));
    }).finally(() => {
      busy.current = false;
      setPending(false);
    });
    return true;
  }, [perform]);

  const working = jobs.some((j) => j.status === "run");
  return { jobs, pending, edited, working, send };
}
