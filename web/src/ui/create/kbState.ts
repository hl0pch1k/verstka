// Состояние базы знаний на «Создать»: какая база (её id — в черновике `verstka.brief_draft`, поле `kb`: страница,
// открытая заново, показывает те же документы), что сейчас добавляется (строка хода), что не взято (строка-ошибка).
// База создаётся на сервере при первом добавлении; пустая база в запрос сборки не попадает (kbRules `kbRequest`).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api";
import { readDraft, writeDraft } from "../../lib/draft";
import { humanError } from "../../lib/errors";
import { plural } from "../../lib/utils";
import type { KbAdded, KbSummary } from "../../types";
import { kbRequest, linkProblem, skippedLine, splitKbFiles } from "./kbRules";

export interface KbState {
  kb: KbSummary | null;
  /** Что сейчас делается: «Читаю 3 документа…», «Открываю страницу…»; null — ничего. */
  busy: string | null;
  /** Что не вышло (не тот формат, страница закрыта входом…); null — всё взято. */
  error: string | null;
  /** Что добавилось последним — строка-итог («Добавлено 2 документа»). */
  done: string | null;
  addFiles(files: File[]): Promise<void>;
  addLink(url: string): Promise<boolean>;
  remove(docId: string): Promise<void>;
  /** Новая пустая база вместо этой (на сервере старая остаётся: на неё ссылаются собранные презентации). */
  clear(): void;
  request: { knowledge_id?: string };
}

const draftKb = (): string | null => {
  const v = readDraft().kb;
  return typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v) ? v : null;
};

const errOf = (e: unknown, fallback: string) => humanError(e instanceof ApiError || e instanceof Error ? e.message : "", fallback);

export function useKbState(): KbState {
  const [kb, setKb] = useState<KbSummary | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const kbNow = useRef<KbSummary | null>(null);
  kbNow.current = kb;

  // база из черновика: её нет на сервере — черновик забывает её
  useEffect(() => {
    const id = draftKb();
    if (!id) return;
    let alive = true;
    api.kb(id).then((s) => alive && setKb(s)).catch((e) => {
      if (alive && e instanceof ApiError && e.status === 404) writeDraft({ kb: null });
    });
    return () => {
      alive = false;
    };
  }, []);

  const ensure = useCallback(async (): Promise<KbSummary> => {
    if (kbNow.current) return kbNow.current;
    const s = await api.createKb("База знаний");
    kbNow.current = s;
    setKb(s);
    writeDraft({ kb: s.id });
    return s;
  }, []);

  const after = useCallback((r: KbAdded, refused: { name: string; reason: string }[] = []) => {
    kbNow.current = r.base;
    setKb(r.base);
    const n = r.added.length;
    setDone(n ? (n === 1 ? `Добавлен «${r.added[0].title}»` : `Добавлено: ${plural(n, "документ", "документа", "документов")}`) : null);
    setError(skippedLine([...refused, ...r.skipped]));
  }, []);

  const addFiles = useCallback(async (files: File[]) => {
    const { take, refused } = splitKbFiles(files.map((f) => ({ name: (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name, size: f.size })));
    const list = take.map((i) => files[i]);
    setDone(null);
    if (!list.length) {
      setError(skippedLine(refused) ?? "Нет документов для базы знаний");
      return;
    }
    setError(null);
    setBusy(list.length === 1 ? `Читаю «${list[0].name}»…` : `Читаю ${plural(list.length, "документ", "документа", "документов")}…`);
    try {
      const s = await ensure();
      after(await api.addKbFiles(s.id, list), refused);
    } catch (e) {
      setError(errOf(e, "Не удалось добавить документы — попробуйте ещё раз"));
    } finally {
      setBusy(null);
    }
  }, [ensure, after]);

  const addLink = useCallback(async (url: string) => {
    const bad = linkProblem(url);
    setDone(null);
    if (bad) {
      setError(bad);
      return false;
    }
    setError(null);
    setBusy("Открываю страницу…");
    try {
      const s = await ensure();
      after(await api.addKbLink(s.id, url.trim()));
      return true;
    } catch (e) {
      setError(errOf(e, "Не удалось открыть страницу — проверьте адрес"));
      return false;
    } finally {
      setBusy(null);
    }
  }, [ensure, after]);

  const remove = useCallback(async (docId: string) => {
    const cur = kbNow.current;
    if (!cur) return;
    // карточка уходит сразу; сервер не ответил — она возвращается со строкой
    setKb({ ...cur, docs: cur.docs.filter((d) => d.id !== docId) });
    setDone(null);
    try {
      const r = await api.removeKbDoc(cur.id, docId);
      kbNow.current = r.base;
      setKb(r.base);
    } catch (e) {
      setKb(cur);
      setError(errOf(e, "Не удалось убрать документ"));
    }
  }, []);

  const clear = useCallback(() => {
    kbNow.current = null;
    setKb(null);
    setError(null);
    setDone(null);
    writeDraft({ kb: null });
  }, []);

  const request = useMemo(() => kbRequest(kb), [kb]);
  return useMemo(() => ({ kb, busy, error, done, addFiles, addLink, remove, clear, request }), [kb, busy, error, done, addFiles, addLink, remove, clear, request]);
}
