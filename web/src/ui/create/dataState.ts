// Состояние второй ступени на «Создать»: файлы с данными (карточки панели «Данные»), брендбук (разбор по событиям задачи,
// карточка, слой) и что важнее при расхождении. Живёт в store (AppProvider зовёт `useDataState` и отдаёт его как
// `data`); черновик — рядом с текстом и параметрами (`verstka.brief_draft`, поле `data`): страница, открытая заново,
// показывает те же файлы и брендбук. Файлы уходят на сервер по одному, по очереди (V2: «разбор по очереди: строка
// статуса сменяется профилем»), — у каждой карточки свой настоящий ход и своя ошибка.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type BrandbookResult } from "../../api";
import { readDraft, writeDraft } from "../../lib/draft";
import { humanError } from "../../lib/errors";
import { errText } from "../../lib/narrate";
import { trackJob } from "../../lib/jobs";
import { uid } from "../../lib/utils";
import type { BrandConflict, BrandPriority, BrandSpec, DatasetSummary, Job } from "../../types";
import {
  BRAND_RUN0, BRAND_STEPS, brandFileName, brandSourceOf, cardName, dataBusy, dataKind, dataRequest, datasetIds, foldBrandEvent, MAX_DATA_BYTES,
  type BrandEvent, type BrandRun, type BrandSource, type DataCard, type DataRequest,
} from "./dataRules";

/** Разбор брендбука: нет; идёт (`run`); все шаги готовы и держатся 560 мс (`done`); гаснет 240 мс (`out`); брендбук
 *  приложен (`on`); не получилось (`fail` — причина в коробке разбора). */
export type BrandPhase = "none" | "run" | "done" | "out" | "on" | "fail";
export interface BrandState {
  phase: BrandPhase;
  source: BrandSource;
  /** Имя файла (папки, «Файл Figma»). */
  file: string;
  /** id на сервере (POST /api/brandbooks), когда он принял файл. */
  id: string | null;
  run: BrandRun;
  spec: BrandSpec | null;
  conflicts: BrandConflict[];
  error: string | null;
  /** Неудачу можно повторить с тем же файлом (не повторить — пример не скачался). */
  canRetry: boolean;
}
export const BRAND0: BrandState = { phase: "none", source: "pdf", file: "", id: null, run: BRAND_RUN0, spec: null, conflicts: [], error: null, canRetry: false };
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
  /** Сборка ушла с этими наборами и брендбуком: на сервере их больше не удаляем («Собрать ещё раз» и «Изменить текст»
   *  той презентации берут их оттуда). */
  markUsed(ids: string[]): void;
}

export interface DataDeps {
  templateId: string | null;
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

interface DataDraft { cards?: DataCard[]; brand?: Pick<BrandState, "source" | "file" | "id" | "spec" | "conflicts"> | null; priority?: BrandPriority; used?: string[] }
function readData(): DataDraft {
  const d = readDraft().data;
  return d && typeof d === "object" ? (d as DataDraft) : {};
}
const cardsFromDraft = (d: DataDraft): DataCard[] =>
  Array.isArray(d.cards) ? d.cards.filter((c) => c && typeof c.key === "string" && (c.status === "done" || c.status === "fail")) : [];
/** В черновике есть карточки файлов с данными (раскладка «Создать» при загрузке страницы). */
export const hasDraftData = (): boolean => cardsFromDraft(readData()).length > 0;
const brandFromDraft = (d: DataDraft): BrandState =>
  d.brand && d.brand.id && d.brand.spec ? { ...BRAND0, ...d.brand, phase: "on", run: { done: BRAND_STEPS.length, facts: {}, brand: d.brand.spec } } : BRAND0;

const tooBig = (f: File) => f.size > MAX_DATA_BYTES;
/** Причина, по которой файл не отправляется вовсе (тип, пустой, размер); null — отправляется. */
function fileProblem(f: File): string | null {
  if (!dataKind(f.name)) return "Такой файл не прочитать — нужен CSV, XLSX, JSON или текст с таблицей";
  if (f.size === 0) return "Файл пустой";
  if (tooBig(f)) return "Файл больше 25 МБ";
  return null;
}
const failText = (e: unknown, fallback: string) => humanError(e instanceof ApiError ? e.message : errText(e), fallback);

export function useDataState(deps: DataDeps): DataState {
  const draft = useMemo(readData, []);
  const [cards, setCards] = useState<DataCard[]>(() => cardsFromDraft(draft));
  const [brand, setBrand] = useState<BrandState>(() => brandFromDraft(draft));
  const [priority, setPriority] = useState<BrandPriority>(() => (draft.priority === "template" ? "template" : "brand"));
  const [exampleBusy, setExampleBusy] = useState(false);
  const cardsRef = useRef(cards);
  cardsRef.current = cards;
  const brandRef = useRef(brand);
  brandRef.current = brand;
  const depsRef = useRef(deps);
  depsRef.current = deps;
  // наборы и брендбуки, с которыми уже собирали: убранные с «Создать», на сервере остаются
  const used = useRef(new Set<string>(Array.isArray(draft.used) ? draft.used.filter((x) => typeof x === "string") : []));
  const [usedN, setUsedN] = useState(used.current.size);
  const dropDataset = (id: string) => {
    if (!used.current.has(id)) void api.deleteDataset(id).catch(() => {});
  };
  const dropBrandbook = (id: string) => {
    if (!used.current.has(id)) void api.deleteBrandbook(id).catch(() => {});
  };

  // ── файлы: очередь по одному
  const files = useRef(new Map<string, File>());
  const pumping = useRef(false);
  const pump = useCallback(async () => {
    if (pumping.current) return;
    pumping.current = true;
    try {
      for (;;) {
        const next = cardsRef.current.find((c) => c.status === "wait");
        if (!next) break;
        const file = files.current.get(next.key);
        if (!file) {
          setCards((cs) => cs.map((c) => (c.key === next.key ? { ...c, status: "fail", error: "Файл больше не доступен — добавьте его снова" } : c)));
          cardsRef.current = cardsRef.current.map((c) => (c.key === next.key ? { ...c, status: "fail" } : c));
          continue;
        }
        const running = (cs: DataCard[]) => cs.map((c) => (c.key === next.key ? { ...c, status: "run" as const } : c));
        cardsRef.current = running(cardsRef.current);
        setCards(running);
        let out: DatasetSummary[] | null = null;
        let error: string | null = null;
        try {
          out = await api.uploadDatasets([file]);
          if (!out.length) error = "Не нашёл таблицу в файле";
        } catch (e) {
          error = failText(e, "Не удалось прочитать файл");
        }
        files.current.delete(next.key);
        const still = cardsRef.current.some((c) => c.key === next.key);
        // карточку убрали, пока файл читался: его наборы на сервере не нужны
        if (!still) {
          for (const s of out ?? []) dropDataset(s.id);
          continue;
        }
        const replace = (cs: DataCard[]): DataCard[] => cs.flatMap((c) => {
          if (c.key !== next.key) return [c];
          if (error || !out?.length) return [{ ...c, status: "fail" as const, error: error ?? "Не нашёл таблицу в файле" }];
          const many = out.length > 1;
          return out.map((s, i) => ({ key: i ? `${c.key}#${i}` : c.key, file: cardName(s, many), kind: s.kind, status: "done" as const, summary: s, error: null }));
        });
        cardsRef.current = replace(cardsRef.current);
        setCards(replace);
      }
    } finally {
      pumping.current = false;
    }
  }, []);

  const addFiles = useCallback((list: File[]) => {
    if (!list.length) return;
    const add: DataCard[] = list.map((f) => {
      const key = uid("dt");
      const problem = fileProblem(f);
      if (!problem) files.current.set(key, f);
      return { key, file: f.name, kind: dataKind(f.name), status: problem ? "fail" : "wait", summary: null, error: problem };
    });
    cardsRef.current = [...cardsRef.current, ...add];
    setCards((cs) => [...cs, ...add]);
    void pump();
  }, [pump]);

  const removeCard = useCallback((key: string) => {
    const c = cardsRef.current.find((x) => x.key === key);
    files.current.delete(key);
    cardsRef.current = cardsRef.current.filter((x) => x.key !== key);
    setCards((cs) => cs.filter((x) => x.key !== key));
    if (c?.summary) dropDataset(c.summary.id);
  }, []);

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

  const finishBrand = useCallback((n: number, res: BrandbookResult) => {
    if (brandSeq.current !== n) return;
    setBrand((b) => ({ ...b, phase: "done", spec: res.brand, conflicts: res.conflicts ?? [], run: { ...b.run, done: BRAND_STEPS.length, brand: res.brand } }));
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
    setBrand({ ...BRAND0, phase: "run", source: brandSourceOf(src), file: brandFileName(src) });
    const failed = (text: string) => {
      if (brandSeq.current === n) setBrand((b) => ({ ...b, phase: "fail", error: text, canRetry: true }));
    };
    void api.uploadBrandbook(src, depsRef.current.templateId).then(({ job_id, brandbook_id }) => {
      if (brandSeq.current !== n) return dropBrandbook(brandbook_id);
      setBrand((b) => ({ ...b, id: brandbook_id }));
      brandStop.current = trackJob(job_id, {
        onEvent: (ev) => {
          if (brandSeq.current === n) setBrand((b) => (b.phase === "run" ? { ...b, run: foldBrandEvent(b.run, ev as BrandEvent) } : b));
        },
        onDone: (job: Job) => {
          const res = job.result as Partial<BrandbookResult> | null;
          if (res?.brand) return finishBrand(n, { brand: res.brand, conflicts: res.conflicts ?? [] });
          // итог задачи без брендбука (старый сервер) — его читаем отдельно
          void api.getBrandbook(brandbook_id, depsRef.current.templateId).then((r) => finishBrand(n, r), (e) => failed(failText(e, "Не удалось разобрать брендбук")));
        },
        onFailed: (job: Job) => failed(humanError(job.error ?? job.message, "Не удалось разобрать брендбук")),
      });
    }, (e) => failed(failText(e, "Не удалось загрузить брендбук")));
  }, [finishBrand]);

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
  }, []);

  // другой шаблон — свои расхождения (тихо: не прочиталось — остаются прежние)
  const brandId = brand.phase === "on" ? brand.id : null;
  const templateId = deps.templateId;
  const askedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!brandId || !templateId) return;
    const key = `${brandId}:${templateId}`;
    if (askedFor.current === null) {
      askedFor.current = key; // первый раз — расхождения уже с этим шаблоном (итог разбора или черновик)
      return;
    }
    if (askedFor.current === key) return;
    askedFor.current = key;
    let alive = true;
    api.getBrandbook(brandId, templateId).then((r) => {
      if (alive) setBrand((b) => (b.id === brandId ? { ...b, spec: r.brand, conflicts: r.conflicts ?? [] } : b));
    }, () => {});
    return () => {
      alive = false;
    };
  }, [brandId, templateId]);

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
        cardsRef.current = [];
        setCards([]);
        addFiles(ex.files);
      }
      if (ex.brandbook) startBrand(ex.brandbook);
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
  }, [addFiles, startBrand]);

  // ── «Изменить текст» презентации: её наборы и брендбук (карточки читаются заново; набора нет — строка карточки)
  const restore = useCallback((p: DataPreset) => {
    if (p.brandPriority) setPriority(p.brandPriority);
    if (p.datasetIds) {
      const now = datasetIds(cardsRef.current);
      const same = now.length === p.datasetIds.length && now.every((id, i) => id === p.datasetIds![i]);
      if (!same) {
        files.current.clear();
        const back: DataCard[] = p.datasetIds.map(() => ({ key: uid("dt"), file: "…", kind: null, status: "run", summary: null, error: null }));
        cardsRef.current = back;
        setCards(back);
        p.datasetIds.forEach((id, i) => {
          const key = back[i].key;
          void api.getDataset(id).then(
            (s) => setCards((cs) => cs.map((c) => (c.key === key ? { ...c, file: s.file, kind: s.kind, status: "done", summary: { ...s, id } } : c))),
            (e) => setCards((cs) => cs.map((c) => (c.key === key ? { ...c, file: "Файл данных", status: "fail", error: e instanceof ApiError && e.status === 404 ? "Файла больше нет на сервере" : failText(e, "Не удалось прочитать файл") } : c))),
          );
        });
      }
    }
    if (p.brandbookId !== undefined) {
      const id = p.brandbookId;
      if (!id) {
        if (brandRef.current.phase !== "none") removeBrandLocal();
      } else if (brandRef.current.id !== id || brandRef.current.phase !== "on") {
        const n = ++brandSeq.current;
        brandStop.current?.();
        void api.getBrandbook(id, depsRef.current.templateId).then((r) => {
          if (brandSeq.current !== n) return;
          askedFor.current = depsRef.current.templateId ? `${id}:${depsRef.current.templateId}` : null;
          setBrand({ ...BRAND0, phase: "on", id, source: r.brand.source === "tokens" ? "json" : r.brand.source === "folder" ? "dir" : r.brand.source,
            file: r.brand.file ?? "", spec: r.brand, conflicts: r.conflicts ?? [], run: { done: BRAND_STEPS.length, facts: {}, brand: r.brand } });
        }, () => {});
      }
    }
    function removeBrandLocal() {
      brandSeq.current += 1;
      brandStop.current?.();
      setBrand(BRAND0);
    }
  }, []);

  const clear = useCallback(() => {
    files.current.clear();
    cardsRef.current = [];
    setCards([]);
  }, []);

  // черновик: разобранные карточки, приложенный брендбук и что важнее — через 300 мс после последней правки
  useEffect(() => {
    const t = window.setTimeout(() => {
      const keep = cards.filter((c) => c.status === "done" || c.status === "fail");
      const b = brand.phase === "on" && brand.id ? { source: brand.source, file: brand.file, id: brand.id, spec: brand.spec, conflicts: brand.conflicts } : null;
      // помним последние 200 использованных (черновик не растёт без конца)
      writeDraft({ data: { cards: keep, brand: b, priority, used: [...used.current].slice(-200) } });
    }, 300);
    return () => window.clearTimeout(t);
  }, [cards, brand, priority, usedN]);
  const markUsed = useCallback((ids: string[]) => {
    for (const id of ids) used.current.add(id);
    setUsedN(used.current.size);
  }, []);

  const ids = useMemo(() => datasetIds(cards), [cards]);
  const request = useMemo(() => dataRequest(ids, brand.phase === "on" ? brand.id : null, priority), [ids, brand.phase, brand.id, priority]);
  return useMemo(() => ({
    cards, addFiles, removeCard, busy: dataBusy(cards), brand, startBrand, retryBrand, dismissBrand, removeBrand, priority, setPriority,
    loadExample, exampleBusy, request, restore, clear, markUsed,
  }), [cards, addFiles, removeCard, brand, startBrand, retryBrand, dismissBrand, removeBrand, priority, loadExample, exampleBusy, request, restore, clear, markUsed]);
}
