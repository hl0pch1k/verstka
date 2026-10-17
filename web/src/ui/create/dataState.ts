// Состояние второй ступени на «Создать»: файлы с данными (карточки панели «Данные»), брендбук (разбор по событиям задачи,
// карточка, слой) и что важнее при расхождении. Живёт в store (AppProvider зовёт `useDataState` и отдаёт его как
// `data`); черновик — рядом с текстом и параметрами (`verstka.brief_draft`, поле `data`): страница, открытая заново,
// показывает те же файлы и брендбук. Файлы уходят на сервер по одному, по очереди (V2: «разбор по очереди: строка
// статуса сменяется профилем»), — у каждой карточки свой настоящий ход и своя ошибка. Правила без React — dataModel.ts.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type BrandbookResult } from "../../api";
import { readDraft, writeDraft } from "../../lib/draft";
import { humanError } from "../../lib/errors";
import { errText } from "../../lib/narrate";
import { trackJob } from "../../lib/jobs";
import { uid } from "../../lib/utils";
import type { BrandPriority, DatasetSummary, Job } from "../../types";
import {
  BRAND_STEPS, brandFileName, brandSizeProblem, brandSourceOf, dataBusy, dataRequest, datasetIds, foldBrandEvent,
  type BrandEvent, type DataCard, type DataRequest,
} from "./dataRules";
import {
  BRAND0, brandOn, conflictsStale, draftOf, expandCard, newCards, nextWaiting, parseDataDraft, sameIds, toSummary, usedAfter, withStatus,
  type BrandState,
} from "./dataModel";

export { BRAND0, type BrandPhase, type BrandState } from "./dataModel";
type BrandInput = File | File[] | { figmaUrl: string };

/** Что берёт «Изменить текст» презентации: её наборы, брендбук и что важнее (generation.json). undefined — не знает
 *  (старая презентация): то, что на «Создать», остаётся. */
export interface DataPreset { datasetIds?: string[]; brandbookId?: string | null; brandPriority?: BrandPriority }

export interface DataState {
  cards: DataCard[];
  /** Файлы с данными (окно выбора, перетаскивание): карточки встают в очередь. */
  addFiles(files: File[]): void;
  /** Убрать карточку (панель уже погасила её): набор удаляется и на сервере. */
  removeCard(key: string): void;
  /** Файлы ещё разбираются: сборка ждёт. */
  busy: boolean;
  brand: BrandState;
  startBrand(src: BrandInput): void;
  /** «Попробовать ещё раз» после неудачи — тот же файл. */
  retryBrand(): void;
  /** Закрыть неудачу разбора — вернуть ленту. */
  dismissBrand(): void;
  /** «Убрать брендбук». */
  removeBrand(): void;
  priority: BrandPriority;
  setPriority(p: BrandPriority): void;
  /** Пример: текст, его файлы и брендбук через те же POST (false — не загрузился: строка у поля «Текст» или, у примера
   *  только брендбука (`where: "brand"`), — в коробке разбора). */
  loadExample(name: string, where?: "text" | "brand"): Promise<boolean>;
  exampleBusy: boolean;
  /** Поля второй ступени запроса сборки. */
  request: DataRequest;
  /** «Изменить текст» презентации: её наборы и брендбук встают на «Создать». */
  restore(p: DataPreset): void;
  /** Всё убрать (новая презентация, «Улучшить готовую»): с «Создать», не с сервера — собранные презентации на них
   *  ссылаются. */
  clear(): void;
  /** Сервер начал сборку с этими наборами и брендбуком: на сервере их больше не удаляем («Собрать ещё раз» и «Изменить
   *  текст» той презентации берут их оттуда). */
  markUsed(ids: string[]): void;
}

export interface DataDeps {
  templateId: string | null;
  /** «Модель пишет тексты»: выключен — брендбук читается без модели зрения. */
  useModels: boolean;
  /** Текст примера встаёт в поле (как «Взять пример»: «Улучшить готовую» кончается). */
  setBrief(text: string): void;
  /** Число слайдов примера. */
  setSlides(n: number): void;
  /** Строка у поля «Текст» (пример не загрузился). */
  fail(text: string): void;
}

/** Галочки держатся 560 мс, разбор гаснет 240 мс (V2 `bbTick`). */
const HOLD_MS = 560;
const OUT_MS = 240;

const readData = () => parseDataDraft(readDraft().data);
/** В черновике есть карточки файлов с данными (раскладка «Создать» при загрузке страницы). */
export const hasDraftData = (): boolean => readData().cards.length > 0;
const failText = (e: unknown, fallback: string) => humanError(e instanceof ApiError ? e.message : errText(e), fallback);

export function useDataState(deps: DataDeps): DataState {
  const draft = useMemo(readData, []);
  const [cards, setCardsState] = useState<DataCard[]>(draft.cards);
  const [brand, setBrand] = useState<BrandState>(draft.brand);
  const [priority, setPriority] = useState<BrandPriority>(draft.priority);
  const priorityRef = useRef(priority);
  priorityRef.current = priority;
  const [used, setUsed] = useState<string[]>(draft.used);
  const [exampleBusy, setExampleBusy] = useState(false);
  // карточки меняются и из асинхронного хода очереди: ссылка — всегда последнее состояние
  const cardsRef = useRef(cards);
  const setCards = useCallback((next: DataCard[] | ((cs: DataCard[]) => DataCard[])) => {
    cardsRef.current = typeof next === "function" ? next(cardsRef.current) : next;
    setCardsState(cardsRef.current);
  }, []);
  const brandRef = useRef(brand);
  brandRef.current = brand;
  const depsRef = useRef(deps);
  depsRef.current = deps;
  const usedRef = useRef(used);
  usedRef.current = used;
  // убранное с «Создать» удаляется и на сервере — если с ним ещё не собирали
  const dropDataset = useCallback((id: string) => {
    if (!usedRef.current.includes(id)) void api.deleteDataset(id).catch(() => {});
  }, []);
  const dropBrandbook = useCallback((id: string) => {
    if (!usedRef.current.includes(id)) void api.deleteBrandbook(id).catch(() => {});
  }, []);

  // ── файлы: очередь по одному
  const files = useRef(new Map<string, File>());
  const pumping = useRef(false);
  const pump = useCallback(async () => {
    if (pumping.current) return;
    pumping.current = true;
    try {
      for (let next = nextWaiting(cardsRef.current); next; next = nextWaiting(cardsRef.current)) {
        const key = next.key;
        const file = files.current.get(key);
        if (!file) {
          setCards((cs) => withStatus(cs, key, "fail", "Файл больше не доступен — добавьте его снова"));
          continue;
        }
        setCards((cs) => withStatus(cs, key, "run"));
        let out: DatasetSummary[] | null = null;
        let error: string | null = null;
        try {
          out = await api.uploadDatasets([file]);
          if (!out.length) error = "Не нашёл таблицу в файле";
        } catch (e) {
          error = failText(e, "Не удалось прочитать файл");
        }
        files.current.delete(key);
        // карточку убрали, пока файл читался: его наборы на сервере не нужны
        if (!cardsRef.current.some((c) => c.key === key)) {
          for (const s of out ?? []) dropDataset(s.id);
          continue;
        }
        setCards((cs) => expandCard(cs, key, out, error));
      }
    } finally {
      pumping.current = false;
    }
  }, [setCards, dropDataset]);

  const addFiles = useCallback((list: File[]) => {
    if (!list.length) return;
    const add = newCards(list, () => uid("dt"));
    add.forEach((c, i) => {
      if (c.status === "wait") files.current.set(c.key, list[i]);
    });
    setCards((cs) => [...cs, ...add]);
    void pump();
  }, [pump, setCards]);

  const removeCard = useCallback((key: string) => {
    const c = cardsRef.current.find((x) => x.key === key);
    files.current.delete(key);
    setCards((cs) => cs.filter((x) => x.key !== key));
    if (c?.summary) dropDataset(c.summary.id);
  }, [setCards, dropDataset]);

  // ── брендбук: задача разбора, шаги — по её событиям
  const brandSeq = useRef(0);
  const brandStop = useRef<(() => void) | null>(null);
  const brandSrc = useRef<BrandInput | null>(null);
  const timers = useRef<number[]>([]);
  const later = (ms: number, fn: () => void) => timers.current.push(window.setTimeout(fn, ms));
  useEffect(() => () => {
    timers.current.forEach((t) => window.clearTimeout(t));
    brandStop.current?.();
  }, []);

  /** Разбор кончился: расхождения — с шаблоном `tplFor` (тем, что был выбран при загрузке). */
  const finishBrand = useCallback((n: number, res: BrandbookResult, tplFor: string | null, prioFor: BrandPriority) => {
    if (brandSeq.current !== n) return;
    setBrand((b) => ({ ...b, phase: "done", spec: res.brand, conflicts: res.conflicts ?? [], tplFor, prioFor,
      applyWarnings: res.warnings ?? [], run: { ...b.run, done: BRAND_STEPS.length, brand: res.brand } }));
    later(HOLD_MS, () => {
      if (brandSeq.current !== n) return;
      setBrand((b) => (b.phase === "done" ? { ...b, phase: "out" } : b));
      later(OUT_MS, () => {
        if (brandSeq.current === n) setBrand((b) => (b.phase === "out" ? { ...b, phase: "on" } : b));
      });
    });
  }, []);

  const startBrand = useCallback((src: BrandInput) => {
    const n = ++brandSeq.current;
    brandStop.current?.();
    brandStop.current = null;
    brandSrc.current = src;
    const old = brandRef.current.id;
    if (old) dropBrandbook(old);
    // больше пределов сервера — не отправляется: причина его же словами, сразу
    const big = "figmaUrl" in src ? null : brandSizeProblem(src);
    if (big) {
      setBrand({ ...BRAND0, phase: "fail", source: brandSourceOf(src), file: brandFileName(src), error: big, canRetry: false });
      return;
    }
    setBrand({ ...BRAND0, phase: "run", source: brandSourceOf(src), file: brandFileName(src) });
    const failed = (text: string) => {
      if (brandSeq.current === n) setBrand((b) => ({ ...b, phase: "fail", error: text, canRetry: true }));
    };
    const tpl = depsRef.current.templateId;
    const prio = priorityRef.current;
    void api.uploadBrandbook(src, tpl, depsRef.current.useModels, prio).then(({ job_id, brandbook_id }) => {
      if (brandSeq.current !== n) return dropBrandbook(brandbook_id);
      setBrand((b) => ({ ...b, id: brandbook_id }));
      brandStop.current = trackJob(job_id, {
        onEvent: (ev) => {
          if (brandSeq.current === n) setBrand((b) => (b.phase === "run" ? { ...b, run: foldBrandEvent(b.run, ev as BrandEvent) } : b));
        },
        onDone: (job: Job) => {
          const res = job.result as Partial<BrandbookResult> | null;
          if (res?.brand) return finishBrand(n, { brand: res.brand, conflicts: res.conflicts ?? [] }, tpl, prio);
          // итог задачи без брендбука (старый сервер) — его читаем отдельно, с нынешним шаблоном
          const now = depsRef.current.templateId;
          void api.getBrandbook(brandbook_id, now, prio).then((r) => finishBrand(n, r, now, prio), (e) => failed(failText(e, "Не удалось разобрать брендбук")));
        },
        onFailed: (job: Job) => failed(humanError(job.error ?? job.message, "Не удалось разобрать брендбук")),
      });
    }, (e) => failed(failText(e, "Не удалось загрузить брендбук")));
  }, [finishBrand, dropBrandbook]);

  const retryBrand = useCallback(() => {
    if (brandSrc.current) startBrand(brandSrc.current);
  }, [startBrand]);
  const dismissBrand = useCallback(() => {
    brandSeq.current += 1;
    brandStop.current?.();
    setBrand((b) => (b.phase === "fail" ? BRAND0 : b));
  }, []);
  const removeBrand = useCallback(() => {
    brandSeq.current += 1;
    brandStop.current?.();
    const id = brandRef.current.id;
    if (id) dropBrandbook(id);
    setBrand(BRAND0);
  }, [dropBrandbook]);

  // расхождения сверены не с выбранным шаблоном (его сменили, пока брендбук разбирался, или позже, или его тогда не
  // было) — читаются заново с ним; тихо: не прочитались — остаются прежние, и попытка повторится со следующей сменой
  // и с тем приоритетом, что выбран: «что в презентации» сервер считает сам (GET …?priority=)
  const templateId = deps.templateId;
  const stale = conflictsStale(brand, templateId, priority);
  const staleId = stale ? brand.id : null;
  useEffect(() => {
    if (!staleId || !templateId) return;
    let alive = true;
    api.getBrandbook(staleId, templateId, priority).then((r) => {
      if (alive) setBrand((b) => (b.id === staleId && b.phase === "on" ? { ...b, spec: r.brand, conflicts: r.conflicts ?? [], tplFor: templateId,
        prioFor: priority, applyWarnings: r.warnings ?? [] } : b));
    }, () => {});
    return () => {
      alive = false;
    };
  }, [staleId, templateId, priority]);

  // ── пример: текст, файлы и брендбук
  const loadExample = useCallback(async (name: string, where: "text" | "brand" = "text") => {
    setExampleBusy(true);
    try {
      const ex = await api.loadExample(name);
      if (ex.manifest.brief) depsRef.current.setBrief(ex.manifest.brief);
      if (ex.manifest.slides) depsRef.current.setSlides(ex.manifest.slides);
      if (ex.files.length) {
        // прежние файлы уходят: пример — целиком свой набор
        for (const c of cardsRef.current) {
          files.current.delete(c.key);
          if (c.summary) dropDataset(c.summary.id);
        }
        setCards([]);
        addFiles(ex.files);
      }
      // брендбук примера уже приложен или разбирается (тот же файл) — второй раз не разбирается
      const b = brandRef.current;
      const same = !!ex.brandbook && (b.phase === "on" || b.phase === "run" || b.phase === "done" || b.phase === "out")
        && (b.file === ex.brandbook.name || b.spec?.file === ex.brandbook.name);
      if (ex.brandbook && !same) startBrand(ex.brandbook);
      return true;
    } catch (e) {
      const text = `Не удалось загрузить пример: ${failText(e, "попробуйте ещё раз")}`;
      if (where === "brand") {
        brandSeq.current += 1;
        setBrand({ ...BRAND0, phase: "fail", file: "Пример брендбука", error: text });
      } else depsRef.current.fail(text);
      return false;
    } finally {
      setExampleBusy(false);
    }
  }, [addFiles, startBrand, setCards, dropDataset]);

  // ── «Изменить текст» презентации: её наборы и брендбук (карточки читаются заново; набора нет — строка карточки)
  const restore = useCallback((p: DataPreset) => {
    if (p.brandPriority) setPriority(p.brandPriority);
    const ids = p.datasetIds;
    if (ids && !sameIds(datasetIds(cardsRef.current), ids)) {
      files.current.clear();
      const back: DataCard[] = ids.map(() => ({ key: uid("dt"), file: "…", kind: null, status: "run", summary: null, error: null }));
      setCards(back);
      ids.forEach((id, i) => {
        const key = back[i].key;
        void api.getDataset(id).then(
          (s) => setCards((cs) => cs.map((c) => (c.key === key ? { ...c, file: s.file, kind: s.kind, status: "done", summary: toSummary(s, id) } : c))),
          (e) => setCards((cs) => cs.map((c) => (c.key === key ? { ...c, file: "Файл данных", status: "fail", error: e instanceof ApiError && e.status === 404 ? "Файла больше нет на сервере" : failText(e, "Не удалось прочитать файл") } : c))),
        );
      });
    }
    if (p.brandbookId !== undefined) {
      const id = p.brandbookId;
      if (!id) {
        if (brandRef.current.phase !== "none") {
          brandSeq.current += 1;
          brandStop.current?.();
          setBrand(BRAND0);
        }
      } else if (brandRef.current.id !== id || brandRef.current.phase !== "on") {
        const n = ++brandSeq.current;
        brandStop.current?.();
        const tpl = depsRef.current.templateId;
        const prio = p.brandPriority ?? priorityRef.current;
        void api.getBrandbook(id, tpl, prio).then((r) => {
          if (brandSeq.current === n) setBrand({ ...brandOn(id, r.brand, r.conflicts ?? [], tpl, prio), applyWarnings: r.warnings ?? [] });
        }, () => {});
      }
    }
  }, [setCards]);

  const clear = useCallback(() => {
    files.current.clear();
    setCards([]);
  }, [setCards]);

  // черновик: разобранные карточки (поля карточки), приложенный брендбук, что важнее, использованные — через 300 мс
  // после последней правки
  useEffect(() => {
    const t = window.setTimeout(() => writeDraft({ data: draftOf(cards, brand, priority, used) }), 300);
    return () => window.clearTimeout(t);
  }, [cards, brand, priority, used]);
  const markUsed = useCallback((ids: string[]) => setUsed((u) => usedAfter(u, ids)), []);

  const ids = useMemo(() => datasetIds(cards), [cards]);
  const request = useMemo(() => dataRequest(ids, brand.phase === "on" ? brand.id : null, priority), [ids, brand.phase, brand.id, priority]);
  return useMemo(() => ({
    cards, addFiles, removeCard, busy: dataBusy(cards), brand, startBrand, retryBrand, dismissBrand, removeBrand, priority, setPriority,
    loadExample, exampleBusy, request, restore, clear, markUsed,
  }), [cards, addFiles, removeCard, brand, startBrand, retryBrand, dismissBrand, removeBrand, priority, loadExample, exampleBusy, request, restore, clear, markUsed]);
}
