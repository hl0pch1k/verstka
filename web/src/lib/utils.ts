import type { Severity } from "../types";

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function uid(prefix = ""): string {
  const rnd = Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
  return prefix ? `${prefix}_${rnd}` : rnd;
}

export const storage = {
  get(key: string): string | null {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key: string, value: string | null) {
    try {
      if (value === null) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, value);
    } catch {
      /* private mode */
    }
  },
};

export const LS = {
  session: "verstka.session_id",
  template: "verstka.template_id",
  generation: "verstka.generation_id",
  agent: "verstka.agent_open",
  brief: "verstka.brief_draft",
};

export function sessionId(): string {
  let id = storage.get(LS.session);
  if (!id) {
    id = uid("s");
    storage.set(LS.session, id);
  }
  return id;
}

export function fmtSeconds(s: number | undefined | null): string {
  if (s === undefined || s === null || Number.isNaN(s)) return "—";
  if (s < 1) return `${(s * 1000).toFixed(0)} мс`;
  if (s < 60) return `${s.toFixed(1)} с`;
  const m = Math.floor(s / 60);
  return `${m} мин ${Math.round(s - m * 60)} с`;
}

export function fmtDate(ts: number | string | undefined | null): string {
  if (ts === undefined || ts === null) return "—";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function fmtPct(v: number | undefined | null, digits = 0): string {
  if (v === undefined || v === null) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function shortSha(s: string | undefined | null, n = 8): string {
  return s ? s.slice(0, n) : "—";
}

export function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return `${n} ${one}`;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return `${n} ${few}`;
  return `${n} ${many}`;
}

export const SEVERITY_LABEL: Record<Severity, string> = { error: "Ошибка", warn: "Предупреждение", info: "Инфо" };

export const KIND_LABEL: Record<string, string> = {
  title: "Титул",
  section: "Раздел",
  agenda: "Повестка",
  bullets: "Список",
  cards: "Карточки",
  two_column: "Две колонки",
  big_number: "Большое число",
  stat_row: "Ряд чисел",
  comparison: "Сравнение",
  timeline: "Таймлайн",
  process: "Процесс",
  table: "Таблица",
  chart: "Диаграмма",
  image_text: "Картинка + текст",
  team: "Команда",
  quote: "Цитата",
  code: "Код",
  mockup: "Мокап",
  thanks: "Финал",
  freeform: "Свободный",
};

export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind;
}

export function scoreTone(score: number | null | undefined): "success" | "warn" | "error" | "neutral" {
  if (score === null || score === undefined) return "neutral";
  if (score >= 90) return "success";
  if (score >= 70) return "warn";
  return "error";
}

export function isLightHex(hex: string): boolean {
  const h = hex.replace("#", "");
  if (h.length < 6) return true;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 160;
}
