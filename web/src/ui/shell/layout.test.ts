// Страница и её стили на любой ширине: viewport — по ширине устройства (иначе телефон и планшет получают колоду
// компьютера 1280 px), границы ширины в CSS — ровно ступени tier.ts, правила стопки не задевают компьютер (от 1280 он
// должен оставаться как на холсте), правила телефона — только на телефоне. Файлы читаются с диска (npm test — из web/).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { TIER_LG, TIER_MD, TIER_XL } from "./tier";

const WEB = process.cwd();
const STYLES = join(WEB, "src/styles");
const css = (name: string) => readFileSync(join(STYLES, name), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
const ALL = readdirSync(STYLES).filter((f) => f.endsWith(".css"));

/** Правила верхнего уровня и блоки @media: [условие или null, текст правил]. Вложенные @container — внутри блока. */
function blocks(src: string): { media: string | null; body: string }[] {
  const out: { media: string | null; body: string }[] = [];
  let i = 0;
  while (i < src.length) {
    const open = src.indexOf("{", i);
    if (open < 0) break;
    const head = src.slice(i, open).trim();
    let depth = 1;
    let j = open + 1;
    while (j < src.length && depth > 0) {
      if (src[j] === "{") depth++;
      else if (src[j] === "}") depth--;
      j++;
    }
    const body = src.slice(open + 1, j - 1);
    if (head.startsWith("@media")) out.push({ media: head.slice(6).trim(), body });
    else if (!head.startsWith("@")) out.push({ media: null, body: `${head}{${body}}` });
    i = j;
  }
  return out;
}

test("viewport — по ширине устройства, без масштаба: телефон и планшет видят свою раскладку, а не колоду 1280", () => {
  const html = readFileSync(join(WEB, "index.html"), "utf8");
  const meta = html.match(/<meta\s+name="viewport"\s+content="([^"]+)"/);
  assert.ok(meta, "в index.html нет viewport");
  const parts = meta[1].split(",").map((p) => p.trim());
  assert.ok(parts.includes("width=device-width"), meta[1]);
  assert.ok(parts.includes("initial-scale=1"), meta[1]);
  assert.ok(!/width=\d/.test(meta[1]), `ширина зашита числом: ${meta[1]}`);
});

test("границы ширины в CSS — ровно ступени tier.ts (768, 1024, 1280), в синтаксисе диапазонов", () => {
  const steps = new Set([TIER_MD, TIER_LG, TIER_XL]);
  for (const f of ALL) {
    for (const m of css(f).matchAll(/@media([^{]+)\{/g)) {
      const q = m[1];
      assert.ok(!/(min|max)-width/.test(q), `${f}: ${q.trim()} — старый синтаксис (щель между 1279.98 и 1280)`);
      for (const w of q.matchAll(/width\s*[<>]=?\s*(\d+(?:\.\d+)?)px/g)) {
        assert.ok(steps.has(Number(w[1])), `${f}: граница ${w[1]} px не ступень tier.ts`);
      }
      for (const w of q.matchAll(/(\d+(?:\.\d+)?)px\s*<=?\s*width/g)) {
        assert.ok(steps.has(Number(w[1])), `${f}: граница ${w[1]} px не ступень tier.ts`);
      }
    }
  }
});

test("stack.css не задевает компьютер: вне запросов стопки — только скрытые по умолчанию элементы стопки", () => {
  const hidden = new Set([".p2-navbtn", ".p2-dim", ".of-short"]);
  for (const b of blocks(css("stack.css"))) {
    if (b.media === null) {
      const rule = b.body.replace(/\s+/g, "");
      const m = rule.match(/^([^{]+)\{display:none;?\}$/);
      assert.ok(m && m[1].split(",").every((s) => hidden.has(s)), `правило вне запроса стопки: ${rule}`);
      continue;
    }
    const stackOnly = /width\s*<\s*(1280|1024|768)px/.test(b.media) || /^\(\s*prefers-reduced-motion/.test(b.media);
    assert.ok(stackOnly, `stack.css: запрос не только для стопки: ${b.media}`);
  }
});

test("правила раскладки телефона (доски M-*) — только внутри запроса телефона", () => {
  const phone = /\.(mp-[\w-]+|mr-[\w-]+|pp-ph\w*|pp-prm\w*|bd-mob|bd-tabs|bd-stp[\w-]*|mp-shut)\b/;
  for (const f of ALL) {
    for (const b of blocks(css(f))) {
      for (const rule of b.body.split("}")) {
        const sel = rule.split("{")[0];
        if (!phone.test(sel)) continue;
        // и без движения (prefers-reduced-motion) — только снимает переходы
        const ok = b.media !== null && (/width\s*<\s*768px/.test(b.media) || /prefers-reduced-motion/.test(b.media));
        assert.ok(ok, `${f}: «${sel.trim()}» вне запроса телефона`);
      }
    }
  }
});
