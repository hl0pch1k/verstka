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
  brief: "verstka.brief_draft",
  /** Идущая сборка ({ gid, request, expected }): страница, открытая заново, находит её и снова следит за ней. */
  build: "verstka.build",
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
  if (s < 60) return `${s.toFixed(1).replace(".", ",")} с`;
  const total = Math.round(s); // round first: 119.6 → «2 мин», never «1 мин 60 с»
  const m = Math.floor(total / 60);
  const rest = total - m * 60;
  return rest === 0 ? `${m} мин` : `${m} мин ${rest} с`;
}

const toDate = (ts: number | string) => (typeof ts === "number" ? new Date(ts * 1000) : new Date(ts));
const dayStart = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();

/** «сегодня, 19:41» · «вчера, 09:05» · «12 сент., 19:41» · «12.09.2025» (unix seconds or an ISO string). */
export function fmtWhen(ts: number | string | undefined | null): string {
  if (ts === undefined || ts === null || ts === "") return "";
  const d = toDate(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  const now = new Date();
  const time = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  const diff = Math.round((dayStart(now) - dayStart(d)) / 86_400_000);
  if (diff === 0) return `сегодня, ${time}`;
  if (diff === 1) return `вчера, ${time}`;
  if (d.getFullYear() === now.getFullYear()) return `${d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}, ${time}`;
  return d.toLocaleDateString("ru-RU");
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
  timeline: "Хронология",
  process: "Процесс",
  table: "Таблица",
  chart: "Диаграмма",
  image_text: "Картинка + текст",
  team: "Команда",
  quote: "Цитата",
  code: "Код",
  mockup: "Макет экрана",
  thanks: "Финал",
  freeform: "Другое",
};

export function kindLabel(kind: string | null | undefined): string {
  return (kind && KIND_LABEL[kind]) || "Слайд";
}
