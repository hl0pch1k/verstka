// The model's state in words: the indicator on the Create screen and the notice above a deck that the built-in
// planner had to plan. The reasons and the advice come from the server (verstka/api/model_status.py).
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

/** «Модель: Qwen3.8-27B — доступна» and friends. `enabled`: the person left the model switched on; `retryIn`: seconds
 * left until a paused model is tried again (counted down by the caller). */
export function modelIndicator(st: ModelsStatus | null, enabled: boolean, retryIn?: number): Indicator | null {
  if (!st) return null;
  if (!st.configured || st.state === "off") return { text: "Модель не подключена · соберёт встроенный планировщик", tone: "off", hint: null, retry: null };
  if (!enabled) return { text: "Модель выключена · соберёт встроенный планировщик", tone: "off", hint: null, retry: null };
  const tone: Tone = st.state === "ok" ? "ok" : st.state === "unknown" ? "neutral" : st.state === "retry" ? "retry" : "warn";
  const left = retryIn ?? st.retry_in ?? 0;
  const retry = left > 0 ? `новая попытка ${waitText(left, st.retry_state)}` : null;
  return { text: st.summary, tone, hint: (st.state === "fallback" || st.state === "down") && st.hint ? keepRanges(st.hint) : null, retry };
}

/** The built-in planner took over because a model failed — and the server knows why (a notice is worth showing). */
function modelFailed(g: Generation): boolean {
  const p = g.planner;
  return !!g.use_models && !!p && p.by_model === false && p.planned_by !== "supplied" && !!p.reason_code && p.reason_code !== "off";
}

const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** «Qwen3.8-27B не ответила: бесплатные модели OpenRouter сейчас перегружены.» */
export function whyNoModel(p: PlannerInfo | null | undefined): string {
  const who = p?.tried_label ?? "Модель";
  if (p?.reason_code === "rejected") return `${who} ответила, но её план не прошёл проверку.`;
  if (!p?.reason) return `${who} не составила план.`;
  return `${who} не ответила: ${p.reason}.`;
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
  /** What happened, one sentence. */
  title: string;
  /** What the deck is based on. */
  basis: string;
  /** What helps (starts with a lowercase letter: it follows «Что поможет:»), or null. */
  help: string | null;
  /** Offer to build the same deck again (the model may answer now or after `retryWait`). */
  retry: boolean;
  /** Seconds before a rebuild makes sense (the button waits, disabled); 0: now. */
  retryWait: number;
  /** The button's words: «Собрать ещё раз» or «Собрать через 2 мин». */
  retryLabel: string;
  /** Offer to add theses (the text is short or only a topic). */
  rewrite: boolean;
}

/** Reasons the same deck built again can get past; a key, an empty account, a missing model or a 400 need a fix first
 * (the server sends `retryable`; this is for older payloads). */
const RETRYABLE = new Set(["congested", "rate", "quota", "timeout", "unreachable", "rejected"]);

/** The live advice already offers the deck's own fix (a top-up of OpenRouter): saying it twice adds nothing. */
function sameFix(liveAdvice: string, deckAdvice: string): boolean {
  if (liveAdvice === deckAdvice) return true;
  const topUp = /пополните (?:счёт )?OpenRouter/i;
  return topUp.test(deckAdvice) && topUp.test(liveAdvice);
}

/** The rebuild button and the advice beside it. Both follow the live state when it is known, so they never disagree:
 * while every model pauses, the live status decides the button (it waits for the link whose pause ends first) and
 * its advice leads; a deck whose own reason needs a fix (a key, an account, a model id) keeps that advice after it.
 * A 400 never gets the button: the same deck gets the same answer from any state of the models. */
export function rebuildOffer(p: PlannerInfo | null | undefined, live?: LiveModel | null): { retry: boolean; wait: number; help: string | null } {
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
  const none = { retry: false, retryWait: 0, retryLabel: "" };
  if (modelFailed(g)) {
    const p = g.planner ?? null;
    const basis = skeleton
      ? "В тексте только тема, поэтому это каркас: разделы с подсказками в заметках."
      : `Слайды собраны встроенным планировщиком строго по вашему тексту${slidesText ? ` — ${slidesText}` : ""}.`;
    const offer = rebuildOffer(p, live);
    const parts = [offer.help ? lowerFirst(offer.help) : null, skeleton || short ? (offer.help ? cap(addTheses) : addTheses) : null].filter(Boolean);
    return {
      title: whyNoModel(p),
      basis,
      help: parts.length ? keepRanges(parts.join(" ")) : null,
      retry: offer.retry,
      retryWait: offer.wait,
      retryLabel: offer.wait > 0 ? `Собрать ${waitText(offer.wait, live?.status?.retry_state)}` : "Собрать ещё раз",
      rewrite: skeleton || short,
    };
  }
  if (skeleton) {
    return { title: "Это каркас: в тексте была только тема.", basis: "Слайды — разделы с подсказками в заметках.", help: addTheses, ...none, rewrite: true };
  }
  if (short) {
    const who = g.planner?.by_model && g.planner.model_label ? `модель ${g.planner.model_label}` : "Verstka";
    return {
      title: `${cap(slidesText)}: материала в тексте меньше.`,
      basis: `План составила ${who} строго по фактам из текста — Verstka их не придумывает.`.replace("составила Verstka", "составлен"),
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
  return `${whyNoModel(g.planner)} План составлен встроенным планировщиком по вашему тексту.${g.planner?.advice ? ` ${g.planner.advice}` : ""}`;
}
