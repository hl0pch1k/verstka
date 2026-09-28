// The model's state in words: the one grey line on the Create screen (only when no model can answer) and the notice
// above a deck built without the model. The advice comes from the server (verstka/api/model_status.py);
// whatever an older server still sends about money, keys, config files or providers never reaches the screen.
import type { Generation, ModelLinkState, ModelsStatus, PlannerInfo, Variant } from "../types";
import { plural } from "./utils";

export type Tone = "ok" | "neutral" | "retry" | "warn" | "off";

export interface Indicator { text: string; tone: Tone; hint: string | null; retry: string | null }

/** «$5–10», «1–5 ₽»: a number range never breaks across lines (word joiners around the dash). */
const keepRanges = (s: string) => s.replace(/(\d)–(\d)/g, "$1\u2060–\u2060$2");

const hhmm = (d: Date) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

const MIN = 60_000;
const HOUR = 3_600_000;
const DAY = 86_400_000;
const MSK = 3 * HOUR; // Moscow is UTC+3 all year

/** When a paused model is tried again, as the reader should see it: rounded up to the next whole minute, so the time
 * shown is never already past while the button still waits. The one exception is OpenRouter's daily reset: the
 * seconds are rounded twice on the way (the server and the countdown), so a quota reset a moment before or after
 * 00:00 UTC is 00:00 UTC — never «после 02:59» for the reset at 03:00 in Moscow. */
export function resetAt(seconds: number, now: number, state?: ModelLinkState | null): number {
  const at = now + Math.max(0, seconds) * 1000;
  if (state === "quota") {
    const midnight = Math.round(at / DAY) * DAY; // the nearest 00:00 UTC
    if (Math.abs(at - midnight) <= 2 * MIN) return midnight;
  }
  return Math.ceil(at / MIN) * MIN;
}

function dayWord(at: number, now: number, dayOf: (t: number) => number, timeZone?: string): string {
  const d = dayOf(at) - dayOf(now);
  if (d <= 0) return "сегодня";
  if (d === 1) return "завтра";
  return new Date(at).toLocaleDateString("ru-RU", { day: "numeric", month: "long", ...(timeZone ? { timeZone } : {}) });
}

const localDay = (t: number) => Math.floor((t - new Date(t).getTimezoneOffset() * MIN) / DAY);
const moscowDay = (t: number) => Math.floor((t + MSK) / DAY);

/** «через 2 мин», «через 3 ч», «завтра после 03:00» (OpenRouter's daily quota resets at 00:00 UTC = 03:00 in Moscow:
 * the same words as the server's advice, whatever the browser's time zone). */
export function waitText(seconds: number, state?: ModelLinkState | null, now: number = Date.now()): string {
  const s = Math.max(0, seconds);
  if (state === "quota" || s >= 6 * 3600) {
    const at = resetAt(s, now, state);
    if (state === "quota" && at % DAY === 0) return `${dayWord(at, now, moscowDay, "Europe/Moscow")} после 03:00`;
    return `${dayWord(at, now, localDay)} после ${hhmm(new Date(at))}`;
  }
  const mins = Math.max(1, Math.ceil(s / 60));
  if (mins < 60) return `через ${mins} мин`; // 3541–3599 s is «через 1 ч», never «через 60 мин»
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m >= 5 ? `через ${h} ч ${m} мин` : `через ${h} ч`;
}

/** The line on the Create screen, or null: nothing is said while any model can answer (ok, unknown, retry, fallback)
 * or when the person switched the model off. `enabled`: the person left the model switched on. */
export function modelIndicator(st: ModelsStatus | null, enabled: boolean, _retryIn?: number): Indicator | null {
  if (!st) return null;
  if (!st.configured || st.state === "off") return { text: "Без модели · быстрая сборка", tone: "off", hint: null, retry: null };
  if (!enabled) return null;
  if (st.state === "down") return { text: "Модель недоступна · соберу без неё", tone: "off", hint: null, retry: null };
  return null;
}

/** Words a person never reads about the model: money, balances, keys, `.env`, config files, provider names. */
const TECH = /\$|₽|пополн|(?<![а-яё])сч[её]т|средств|баланс|(?<![а-яё])ключ|\.env|groq|openrouter|cloud\.ru|configs\/|\.ya?ml|файл\S* настроек/i;
const RETRY_LATER = "Модель временно недоступна — соберите позже";
const UNAVAILABLE = "Модель недоступна";
/** The server's own «Модель недоступна.» is the same words. */
const isUnavailable = (help: string | null) => help?.replace(/\.$/, "") === UNAVAILABLE;
const stop = (s: string) => (/[.!?…]$/.test(s) ? s : `${s}.`);
/** Sentences joined into one text: a one-line label (no stop of its own) gets one before the next sentence; the last
 *  keeps its stop only in running text (`closed`), so a lone «Модель недоступна» stays a label. */
const sentences = (parts: Array<string | null | undefined>, closed = false) => {
  const xs = parts.filter((x): x is string => !!x);
  return xs.map((x, i) => (i < xs.length - 1 || closed ? stop(x) : x)).join(" ");
};

/** A provider's retry timer («Пауза после сбоя закончилась…», «…через 2 мин»): not a person's business (copy rule 6). */
const TIMER = /пауз|через\s+\d/i;
/** A sentence without its timer: «Соберите ещё раз через 2 мин.» and an older server's «Пауза после сбоя закончилась —
 *  соберите ещё раз.» both say «Соберите ещё раз.» (the rebuild button waits by itself). */
const untimed = (x: string) =>
  cap(x.replace(/^пауза[^—–-]*[—–-]\s*/i, "").replace(/\s+через\s+\d+(?:[.,]\d+)?\s*(?:мин|ч|сек|с)[а-яё]*(?:\s+\d+\s*мин[а-яё]*)?/gi, ""));

/** The advice without its technical sentences (an older server's «… или пополните OpenRouter на $5–10», «Проверьте
 * ключ …», «Пауза после сбоя закончилась…»): the clause about money goes, the rest of the sentence stays. Null when
 * nothing plain is left. */
export function plainAdvice(text: string | null | undefined): string | null {
  if (!text) return null;
  const t = text.replace(/[,;]?\s+или\s+(?:пополните|включите|проверьте|выберите)[\s\S]*?(?=[.!?…](?:\s|$))/gi, "");
  const kept = t
    .split(/(?<=[.!?…])\s+/)
    .map((x) => untimed(x.trim()))
    .filter((x) => x && !TECH.test(x) && !TIMER.test(x));
  return kept.length ? kept.join(" ") : null;
}

/** «Модель не ответила: …» — the reason in plain words, from its code (the server's `reason` may name providers). */
const WHY: Record<string, string> = {
  congested: "сервер модели перегружен",
  rate: "слишком много запросов за минуту",
  quota: "дневной лимит запросов исчерпан",
  timeout: "время на ответ вышло",
  unreachable: "нет связи с сервером модели",
};

/** The built-in planner took over because a model failed — and the server knows why (a notice is worth showing). */
function modelFailed(g: Generation): boolean {
  const p = g.planner;
  return !!g.use_models && !!p && p.by_model === false && p.planned_by !== "supplied" && !!p.reason_code && p.reason_code !== "off";
}

const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** Why the model did not plan, as a plain clause for any screen («сервер модели перегружен»), or null. The server's
 * `reason` names providers and money («на счёте OpenRouter нет средств»): it is shown only when it has none of that. */
export function reasonWords(p: PlannerInfo | null | undefined): string | null {
  const code = p?.reason_code ?? "";
  if (!code || code === "off") return null;
  if (code === "rejected") return "план модели не прошёл проверку";
  if (code === "no_credits" || code === "auth" || code === "missing") return "модель недоступна";
  if (code === "error") return "модель вернула ошибку";
  return WHY[code] ?? (p?.reason && !TECH.test(p.reason) ? p.reason : null);
}

/** «Модель не ответила: сервер модели перегружен» — a one-line label, no stop. It says «Модель», never a backend
 *  name (the name lives in the «Файлы» tab). */
export function whyNoModel(p: PlannerInfo | null | undefined): string {
  const who = "Модель";
  const code = p?.reason_code ?? "";
  if (code === "rejected") return `${who} ответила, но её план не прошёл проверку`;
  if (code === "no_credits" || code === "auth" || code === "missing") return `${who} сейчас недоступна`;
  if (code === "error") return `${who} вернула ошибку`;
  const why = reasonWords(p);
  return why ? `${who} не ответила: ${why}` : `${who} не составила план`;
}

/** What the page knows about the model right now, for the notice above a deck. */
export interface LiveModel {
  status: ModelsStatus | null;
  /** The deck is the newest one built with the model: the live state is about the same failure. */
  latest: boolean;
  /** Seconds until a paused model is tried again, counted down by the caller. */
  retryIn: number;
}

export interface DeckNotice {
  /** What happened: a one-line label without a stop. */
  title: string;
  /** What the deck is based on. */
  basis: string;
  /** What helps (starts with a lowercase letter: it follows «Что поможет:»), or null. */
  help: string | null;
  /** Offer to build the same deck again (the model may answer now or after `retryWait`). */
  retry: boolean;
  /** Seconds before a rebuild makes sense (the button waits, disabled); 0: now. */
  retryWait: number;
  /** The button's words, always «Собрать ещё раз»: while it waits (`retryWait`) it is disabled, never a timer. */
  retryLabel: string;
  /** Offer to add theses (the text is short or only a topic). */
  rewrite: boolean;
  /** «warn»: the deck is thinner than it could be; «info»: all is well, one thing to know (the agent wrote the text). */
  tone: "warn" | "info";
  /** Offer «Показать текст»: the text the agent wrote from the topic. */
  showText: boolean;
}

/** Reasons the same deck built again can get past; a key, an empty account, a missing model or a 400 need a fix first
 * (the server sends `retryable`; this is for older payloads). */
const RETRYABLE = new Set(["congested", "rate", "quota", "timeout", "unreachable", "rejected"]);

/** The live advice already offers the deck's own fix (an older server's word about a top-up): saying it twice adds nothing. */
function sameFix(liveAdvice: string, deckAdvice: string): boolean {
  if (liveAdvice === deckAdvice) return true;
  const topUp = /пополните (?:счёт )?OpenRouter/i;
  return topUp.test(deckAdvice) && topUp.test(liveAdvice);
}

/** The rebuild button and the advice beside it. Both follow the live state when it is known, so they never disagree:
 * while every model pauses, the live status decides the button (it waits for the link whose pause ends first) and
 * its advice leads; a deck whose own reason needs a fix (a key, an account, a model id) keeps that advice after it.
 * A 400 never gets the button: the same deck gets the same answer from any state of the models. The advice is plain:
 * a sentence about money or keys is dropped, and when nothing is left it says the model is (temporarily) unavailable. */
export function rebuildOffer(p: PlannerInfo | null | undefined, live?: LiveModel | null): { retry: boolean; wait: number; help: string | null } {
  const o = offerOf(p, live);
  return { ...o, help: o.help ? plainAdvice(o.help) ?? (o.retry ? RETRY_LATER : UNAVAILABLE) : null };
}

function offerOf(p: PlannerInfo | null | undefined, live?: LiveModel | null): { retry: boolean; wait: number; help: string | null } {
  const reasonFits = p?.retryable ?? RETRYABLE.has(p?.reason_code ?? "");
  const st = live?.status ?? null;
  if (!st || !st.configured || st.state === "off") return { retry: reasonFits, wait: 0, help: p?.advice ?? null };
  const down = st.state === "down";
  // a 400 is about these inputs: the same deck built again gets the same answer, whenever the pause ends
  const sameAnswer = p?.reason_code === "error";
  let retry: boolean;
  if (down) {
    // «false»: every model waits for a fix (a key, an account) — say what to fix
    retry = !sameAnswer && (st.retryable ?? reasonFits);
  } else {
    // a rebuild helps when the reason passes by itself — or, for the newest deck, when a model answers again now. A 400
    // is about these inputs: the same model answering others does not make the same deck pass (another model might)
    const answersAgain = st.state === "fallback" || (st.state === "ok" && !sameAnswer);
    retry = reasonFits || (!!live?.latest && answersAgain);
  }
  const wait = retry && down ? Math.max(0, live?.retryIn ?? st.retry_in ?? 0) : 0;
  if (!st.advice || !(retry || down)) return { retry, wait, help: p?.advice ?? null };
  if (down) {
    // no button while the paused links could be retried: their advice («соберите ещё раз через …») would promise a
    // rebuild the notice does not offer, so the deck's own fix is the whole help
    if (!retry && st.retryable !== false) return { retry, wait, help: p?.advice ?? null };
    // the live advice says when to build again (or what the paused links need); the deck's own fix stays after it
    const fix = !reasonFits && p?.advice && !sameFix(st.advice, p.advice) ? p.advice : null;
    return { retry, wait, help: fix ? `${st.advice} ${fix}` : st.advice };
  }
  // while a model answers, the deck's word about the paid model stays after the live advice
  return { retry, wait, help: p?.steady ? `${st.advice} ${p.steady}` : st.advice };
}

const lowerFirst = (s: string) => (s.length > 1 && s[1] === s[1].toLowerCase() ? s[0].toLowerCase() + s.slice(1) : s);

/** The notice above a deck, or null when there is nothing to say. `total`: slides of the shown variant; `live`: the
 * model's state now (the rebuild button and its advice follow it). */
export function deckNotice(g: Generation, v: Variant, total: number, live?: LiveModel | null): DeckNotice | null {
  const skeleton = v.outline?.planned_by === "skeleton";
  const asked = g.slides ?? null;
  const short = !!asked && asked - total >= 3 && !g.outline_supplied;
  const slidesText = short ? `вышло ${plural(total, "слайд", "слайда", "слайдов")} вместо ${asked}` : "";
  const addTheses = "допишите тезисы и цифры — слайды станут содержательнее.";
  const none = { retry: false, retryWait: 0, retryLabel: "", tone: "warn" as const, showText: false };
  const w = g.writer ?? null;
  // writer mode: the text was a topic and the agent wrote the deck's text — a calm note, the text one click away
  if (w?.status === "written" && w.text) {
    const src = w.source?.title;
    const basis = src ? `По статье Википедии «${src}».` : "Агент писал по своим знаниям — даты и цифры могут быть неточны.";
    const want = w.asked ?? asked;
    // the asked slide count is a promise in writer mode: any shortfall is said (not only 3 or more)
    const fewer = !!want && want > total ? ` Вышло ${plural(total, "слайд", "слайда", "слайдов")} вместо ${want}.` : "";
    return { title: "Текст написал агент — проверьте факты", basis: basis + fewer, help: null, ...none, rewrite: false, tone: "info", showText: true };
  }
  if (skeleton && (w?.status === "private" || w?.status === "refused")) {
    return {
      title: w.status === "private" ? "Это каркас: о вашей теме знаете только вы" : "Это каркас: на эту тему агент текст не пишет",
      basis: "Слайды — разделы с подсказками в заметках.",
      help: addTheses,
      ...none,
      rewrite: true,
    };
  }
  if (modelFailed(g)) {
    const p = g.planner ?? null;
    const basis = skeleton
      ? w?.status === "failed" || w?.status === "skipped"
        ? "Модель не написала текст по теме, поэтому это каркас."
        : "В тексте только тема, поэтому это каркас: разделы с подсказками в заметках."
      : `Собрано по вашему тексту без модели${slidesText ? ` — ${slidesText}` : ""}.`;
    const offer = rebuildOffer(p, live);
    // «Модель недоступна» after the title «Модель сейчас недоступна» says nothing new
    const help = isUnavailable(offer.help) ? null : offer.help;
    const parts = [help ? lowerFirst(help) : null, skeleton || short ? (help ? cap(addTheses) : addTheses) : null];
    return {
      title: whyNoModel(p),
      basis,
      help: parts.some(Boolean) ? keepRanges(sentences(parts)) : null,
      retry: offer.retry,
      retryWait: offer.wait,
      retryLabel: "Собрать ещё раз",
      rewrite: skeleton || short,
      tone: "warn",
      showText: false,
    };
  }
  if (skeleton) {
    return { title: "Это каркас: в тексте была только тема", basis: "Слайды — разделы с подсказками в заметках.", help: addTheses, ...none, rewrite: true };
  }
  if (short) {
    return {
      title: `${cap(slidesText)}: в тексте меньше материала`,
      basis: "План составлен строго по фактам из текста.",
      help: addTheses,
      ...none,
      rewrite: true,
    };
  }
  return null;
}

/** One line for the chat after a deck whose plan no model wrote because the model failed. */
export function silentNote(g: Generation): string {
  if (!modelFailed(g)) return "";
  return sentences([whyNoModel(g.planner), "Собрал по вашему тексту без модели", plainAdvice(g.planner?.advice)], true);
}
