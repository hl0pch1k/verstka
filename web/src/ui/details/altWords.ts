// «Другие формы» вкладки «Почему так» словами интерфейса (логика `altWords`/`reasonAfter` — как до «Слоёв»):
// «**Таблица** — позволит выписать рядом f(x) и F(x)…». Название — как у вкладок («Ряд чисел»; тип диаграммы в начале
// довода становится названием), довод — после тире, с маленькой буквы, без точки одной фразы. Повтор названия в начале
// довода («Таблица позволит…», «Форма «карточки» позволяет…») снимается, только когда за ним идёт глагол — тогда
// глагол согласуется с названием; иначе фраза остаётся целой («компактная таблица «Год — Событие»…»).
import { plainWords } from "../../lib/agent";
import { KIND_LABEL, kindLabel } from "../../lib/utils";
import type { SlideAlternativeInfo } from "../../types";

const CHART_HEAD = /^((?:[а-яё]+\s+)?(?:диаграмма|график)(?:\s+с\s+[а-яё]+)?)\s*:\s*(.+)$/is;
const ADJECTIVE = /(?:ий|ый|ой|ая|яя|ое|ее|ые|ие)$/i;
const NUMERAL = /^(?:два|две|три|четыре)$/i;
const CHART_NOUNS = ["диаграмма", "график"];
const VERB = /^(?:[а-яё]*[аеиоуяы](?:л|ла|ло|ли)|[а-яё]+(?:ет|ёт|ит|ют|ят|ут))$/i;

type Agreement = "m" | "f" | "n" | "p";
const agreementOf = (noun: string): Agreement => (/[ыи]$/i.test(noun) ? "p" : /[ая]$/i.test(noun) ? "f" : /[оеё]$/i.test(noun) ? "n" : "m");
const PAST: Record<Agreement, string> = { m: "л", f: "ла", n: "ло", p: "ли" };

/** «таблица» и «таблицей»: одно слово в другом падеже; «табличное» — другое. */
function sameWord(a: string, b: string): boolean {
  const x = a.toLowerCase();
  const y = b.toLowerCase();
  const stem = y.length <= 4 ? y : y.slice(0, -1);
  return x.startsWith(stem) && x.length <= y.length + 2;
}

/** Глагол, сказанный об одном существительном, — о другом: «график показал» → «(диаграмма) показала». */
function agree(verb: string, from: Agreement, to: Agreement): string {
  if (from === to) return verb;
  const past = /^([а-яё]*[аеиоуяы])(?:л|ла|ло|ли)$/i.exec(verb);
  if (past) return past[1] + PAST[to];
  if (to === "p" && from !== "p") {
    if (/^может$/i.test(verb)) return "могут";
    if (/[аеиоуяю]ет$/i.test(verb) || /ёт$/i.test(verb)) return verb.replace(/[её]т$/i, "ют");
    if (/ит$/i.test(verb)) return verb.replace(/ит$/i, "ят");
  }
  return verb;
}

/** Первое слово после снятого начала — глагол (или «бы»): только тогда повтор названия можно снять. */
const verbNext = (rest: string) => {
  const w = rest.replace(/^[\s,:;—–-]+/, "").split(/\s+/)[0] ?? "";
  return VERB.test(w) || /^бы$/i.test(w);
};

function reasonAfter(label: string, text: string): string {
  let t = text.trim();
  const words = label.toLowerCase().split(/\s+/).filter(Boolean);
  const head = words.find((w) => !ADJECTIVE.test(w) && !NUMERAL.test(w)) ?? words[words.length - 1] ?? "";
  let subject: Agreement | null = null;
  const form = /^Форма\s+«[^«»]+»\s*/i.exec(t);
  if (form && verbNext(t.slice(form[0].length))) {
    t = t.slice(form[0].length);
    subject = "f";
  } else if (label && t.toLowerCase().startsWith(label.toLowerCase()) && !/^[а-яёa-z0-9]/i.test(t.slice(label.length)) && verbNext(t.slice(label.length))) {
    t = t.slice(label.length);
    subject = agreementOf(head);
  } else if (head) {
    const m = /^(?:([а-яё]+)\s+)?([а-яё]+)(?=[\s,.:—–-]|$)/i.exec(t);
    if (m) {
      const [lead, noun] = m[1] && ADJECTIVE.test(m[1]) ? [m[0], m[2]] : [m[1] ?? m[2], m[1] ?? m[2]];
      const synonyms = CHART_NOUNS.includes(head) ? CHART_NOUNS : [head];
      if (synonyms.some((w) => sameWord(noun, w)) && verbNext(t.slice(lead.length))) {
        t = t.slice(lead.length);
        subject = agreementOf(noun);
      }
    }
  }
  t = t.replace(/^[\s,:;—–-]+/, "");
  // «(Таблица) бы ясно показала…» → «ясно показала бы…»
  const lone = /^бы\s+/i.exec(t);
  if (lone) t = t.slice(lone[0].length);
  const parts = t.split(" ");
  const at = parts.slice(0, 3).findIndex((w) => VERB.test(w));
  if (at >= 0) {
    if (subject) {
      const to = agreementOf(head);
      parts[at] = agree(parts[at], subject, to);
      for (let i = at + 1; i < parts.length; i++) {
        if (/^[а-яё]{4,}(?:ет|ёт|ит)$/i.test(parts[i]) && (/,$/.test(parts[i - 1]) || /^и$/i.test(parts[i - 1]))) parts[i] = agree(parts[i], subject, to);
      }
    }
    if (lone) parts[at] += " бы";
    t = parts.join(" ");
  } else if (lone) t = `бы ${t}`;
  if (/^[А-ЯЁA-Z][а-яёa-z]/.test(t)) t = t.charAt(0).toLowerCase() + t.slice(1);
  if (/[^.]\.$/.test(t) && !/[.!?…]\s/.test(t.slice(0, -1))) t = t.slice(0, -1);
  return t;
}

const capital = (t: string) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);

export function altWords(a: SlideAlternativeInfo): { name: string; text: string } {
  let label = a.kind && KIND_LABEL[a.kind] ? kindLabel(a.kind) : a.label ?? "";
  let text = a.text ? plainWords(a.text) : "";
  const m = CHART_HEAD.exec(text);
  if (m) {
    label = m[1].toLowerCase();
    text = m[2];
  }
  return label ? { name: capital(label), text: reasonAfter(label, text) } : { name: "", text: capital(text.trim()) };
}
