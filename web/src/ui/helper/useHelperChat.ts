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
//    тихая строка «Это другая презентация…», не перечиталась — тихая строка с причиной и «Обновить» (noteView);
//  · open_tab — лист «Подробнее» на нужной вкладке (openTabSteps), если открыта та презентация, о которой ответ;
//  · busy — вариант занят другой правкой: просьба встаёт в очередь (ответ говорит это) и уходит ещё раз, когда вариант
//    свободен и ответ прежней правки уже в ленте; очередь одна, просьбы идут по порядку.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { sessionId, uid } from "../../lib/utils";
import { useApp } from "../../store";
import type { ChatAction, ChatResponse, Generation, Job } from "../../types";
import { workKey } from "../details/variantWork";
import {
  asEditResult, asFixResult, chatFailText, chatTarget, describeFixes, editFailText, editLink, feedProgress, planActions, queueHead, queuedText,
  queueStartText, reloadFailText, OTHER_DECK, QUEUE_GAVE_UP, QUEUE_TRIES, QUEUE_WAIT,
  type EditAction, type Edited, type FeedJob, type FeedNote, type FixOutcome, type Queued,
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
  /** Просьб ждёт в очереди (их вариант меняется по прежней). */
  queued: number;
  /** Отправить вопрос; false — не ушёл (пусто или ответ ещё не пришёл). */
  send(text: string): boolean;
}

/** Чем кончилось перечитывание после правки: презентация на экране обновилась; открыта другая; не перечиталась. */
type Reload = { kind: "open"; g: Generation } | { kind: "other" } | { kind: "failed"; error: unknown };

const now = () => Date.now() / 1000;
type Target = Queued["target"];
type BusyAction = Extract<ChatAction, { type: "busy" }>;

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
  /** Очередь просьб, чей вариант был занят; `settling` — правок из чата, чей ответ ещё не в ленте (просьба из очереди
   *  уходит после него); `wake` будит очередь (правка дописала ответ, пришло время повтора). */
  const queue = useRef<Queued[]>([]);
  const [queued, setQueued] = useState(0);
  const settling = useRef(0);
  const [wake, setWake] = useState(0);
  const kick = useCallback(() => setWake((w) => w + 1), []);

  const addJob = useCallback((id: string, label: string) => {
    setJobs((js) => (js.some((j) => j.id === id) ? js : [...js, { id, label, ts: now(), progress: 0, status: "run" }]));
  }, []);
  const settleJob = useCallback((id: string, status: "done" | "failed") => {
    setJobs((js) => js.map((j) => (j.id === id ? { ...j, status, progress: status === "done" ? 1 : j.progress } : j)));
  }, []);
  const noteSeq = useRef(0);
  const addNote = useCallback((text: string, refresh?: string) => {
    const id = `n${Date.now()}-${++noteSeq.current}`;
    setNotes((ns) => [...ns, { id, text, ts: now(), refresh }]);
    return id;
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
  /** Что сказать в ленте после перечитывания: открыта другая — тихая строка; не перечиталась — тихая строка с причиной
   *  и «Обновить» (пока презентация несвежая). */
  const tellReload = useCallback((r: Reload | null, gid: string | null) => {
    if (r?.kind === "other") addNote(OTHER_DECK);
    else if (r?.kind === "failed") {
      const id = addNote(reloadFailText(r.error), gid ?? undefined);
      // строка «не обновилась» с «Обновить» теперь в ленте — живая, пока длится эта несвежесть; компактный вид
      // результата её не повторяет
      if (gid) latest.current.noteFeedRefresh(gid, id);
    }
  }, [addNote]);

  const followEdit = useCallback((a: EditAction) => {
    const s = latest.current;
    const gid = a.generation_id;
    // готово — презентация перечитывается и ответ встаёт в ленту; просьба из очереди уходит после него
    const done = async (job: Job) => {
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
      // под ответом — «Показать слайд N», пока на экране та презентация
      latest.current.pushMessage("assistant", r?.reply ?? "Готово.", after?.kind === "open" ? editLink(r, gid, a) : undefined);
      tellReload(after, gid);
    };
    let open = true;
    settling.current += 1;
    const settled = () => {
      if (!open) return;
      open = false;
      settling.current -= 1;
      kick();
    };
    addJob(a.job_id, "Меняю презентацию");
    s.runJob(a.job_id, "Меняю презентацию", {
      kind: "edit", area: "result", quiet: true, generation: gid, target: { generation: gid, strategy: a.strategy, slide: a.slide ?? 0 },
      onDone: (job: Job) => done(job).finally(settled),
      onFailed: (job: Job) => {
        settleJob(a.job_id, "failed");
        latest.current.pushMessage("assistant", editFailText(job.error ?? job.message));
        settled();
      },
    });
  }, [addJob, settleJob, reloadDeck, tellReload, kick]);

  const followFixes = useCallback((list: { strategy: string; job_id: string }[], gid: string | null) => {
    if (!list.length) return;
    const s = latest.current;
    const open = s.generation && s.generation.id === gid ? s.generation : null;
    const before = (strategy: string) => open?.variants.find((v) => v.strategy === strategy)?.audit?.summary.score ?? null;
    const outcomes: FixOutcome[] = list.map((j) => ({ strategy: j.strategy, before: before(j.strategy), done: false, result: null, error: null }));
    let left = list.length;
    // итог исправлений встаёт в ленту раньше, чем уходит просьба из очереди
    settling.current += 1;
    const settle = async () => {
      left -= 1;
      if (left > 0) return;
      try {
        let after: Reload | null = null;
        if (gid && outcomes.some((o) => o.done)) {
          void latest.current.refreshGenerations();
          after = await reloadDeck(gid);
        }
        latest.current.pushMessage("assistant", describeFixes(outcomes, latest.current.strategyTitle));
        tellReload(after, gid);
      } finally {
        settling.current -= 1;
        kick();
      }
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
  }, [addJob, settleJob, reloadDeck, tellReload, kick]);

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

  /** Вопрос серверу. `item` — просьба из очереди (её вопрос уже в ленте). Вариант занят другой правкой (`busy`) —
   *  просьба встаёт в очередь (новая — в конец, с ответом, что она ждёт; повторная — обратно первой, молча). */
  const ask = useCallback((message: string, target: Target, item: Queued | null) => {
    busy.current = true;
    setPending(true);
    setEdited(null);
    const s = latest.current;
    const sent = target.generation_id;
    void api.chat({ session_id: sessionId(), message, template_id: s.templateId, ...target }).then((res) => {
      const hold = (res.actions ?? []).find((a): a is BusyAction => a.type === "busy");
      if (!hold) {
        latest.current.pushMessage("assistant", res.reply);
        return perform(res, res.generation_id ?? sent);
      }
      const tries = (item?.tries ?? 0) + 1;
      if (tries > QUEUE_TRIES) return latest.current.pushMessage("assistant", QUEUE_GAVE_UP);
      const q: Queued = { id: item?.id ?? uid("q"), message, target, key: workKey(hold.generation_id, hold.strategy), tries, after: Date.now() + (item ? QUEUE_WAIT : 1000) };
      queue.current = item ? [q, ...queue.current] : [...queue.current, q];
      if (!item) latest.current.pushMessage("assistant", queuedText(message, queue.current.length - 1));
      setQueued(queue.current.length);
    }, (e: unknown) => {
      latest.current.pushMessage("assistant", chatFailText(e));
    }).finally(() => {
      busy.current = false;
      setPending(false);
      kick();
    });
  }, [perform, kick]);

  const send = useCallback((raw: string) => {
    const message = raw.trim();
    if (!message || busy.current) return false;
    const s = latest.current;
    s.pushMessage("user", message);
    // вопрос — о том, что на экране: на результате — открытая презентация, её вариант и слайд («почему слайд 3 такой» —
    // про него), на «Сборке» — собираемая, на «Создать» — никакая; ответ действует только на неё (planActions), даже
    // если пока ждали, открыли другую
    const target = chatTarget({
      screen: s.ui.screen, open: s.generationId, strategy: s.activeStrategy, slide: s.generation ? s.selectedSlide : null,
      building: s.buildJob?.generation ?? null,
    });
    ask(message, target, null);
    return true;
  }, [ask]);

  // очередь: первая просьба уходит, когда ответа никто не ждёт, правки из чата дописали свой ответ, её вариант свободен
  // и пришло время повтора; время ещё не пришло — будильник к нему
  const busyKeys = app.busyVariants;
  const settleWait = useRef<number | null>(null);
  useEffect(() => {
    if (!queued || pending) return;
    const head = queueHead(queue.current, busyKeys, Date.now());
    if (!head) {
      settleWait.current = null;
      const first = queue.current[0];
      if (!first || busyKeys.includes(first.key)) return;
      const t = window.setTimeout(kick, Math.max(0, first.after - Date.now()) + 20);
      return () => window.clearTimeout(t);
    }
    // вариант свободен, а ответ прежней работы из чата ещё не в ленте — ждём его, но не дольше 8 с (перечитывание
    // презентации зависло)
    if (settling.current > 0) {
      const since = (settleWait.current ??= Date.now());
      const left = since + 8000 - Date.now();
      if (left > 0) {
        const t = window.setTimeout(kick, left + 20);
        return () => window.clearTimeout(t);
      }
    }
    settleWait.current = null;
    queue.current = queue.current.slice(1);
    setQueued(queue.current.length);
    addNote(queueStartText(head.message));
    ask(head.message, head.target, head);
  }, [queued, pending, wake, busyKeys, ask, addNote, kick]);

  const working = jobs.some((j) => j.status === "run");
  return { jobs, notes, pending, edited, working, queued, send };
}
