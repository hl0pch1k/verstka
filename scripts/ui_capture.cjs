// UI capture for visual QA: every screen and panel of the web app at desktop sizes, as PNG files.
//   node scripts/ui_capture.cjs OUT_DIR [--build | --build=live] [--only=build] [--sizes=1440x900,1366x768,1280x720]
// Needs the server on 127.0.0.1:8000 (verstka serve) and Google Chrome; Playwright is taken from PLAYWRIGHT_PATH or
// the npx cache. --build captures the build screen by replaying the agent's recorded steps of the newest short deck
// (the job API is answered by the script: no model calls, no new deck in «Мои презентации»); --build=live starts a
// real generation of the short example brief instead.
const fs = require("fs");
const path = require("path");

function playwright() {
  const cands = [process.env.PLAYWRIGHT_PATH, ...(() => {
    const root = path.join(require("os").homedir(), ".npm/_npx");
    try { return fs.readdirSync(root).map((d) => path.join(root, d, "node_modules/playwright")); } catch { return []; }
  })()].filter(Boolean);
  for (const c of cands) { try { return require(c); } catch {} }
  return require("playwright");
}

const BASE = process.env.VERSTKA_URL || "http://127.0.0.1:8000";
const out = process.argv[2] || "ui_shots";
const buildArg = process.argv.find((a) => a === "--build" || a.startsWith("--build="));
const onlyBuild = process.argv.includes("--only=build"); // just the replayed build screen (implies --build)
const build = buildArg ? (buildArg === "--build=live" ? "live" : "replay") : onlyBuild ? "replay" : null;
const sizesArg = (process.argv.find((a) => a.startsWith("--sizes=")) || "--sizes=1440x900,1366x768").split("=")[1];
const sizes = sizesArg.split(",").map((s) => s.split("x").map(Number));
fs.mkdirSync(out, { recursive: true });

const SHORT = "gen_short", LONG = "gen_long";

// The agent's steps of a finished deck, as the job stream sent them: agent.json of its run folder, else the variants'
// own timelines from the API (shared steps once).
async function recordedSteps(page, g) {
  try {
    const file = path.join(__dirname, "..", "workspace", "runs", g.id, "agent.json");
    const events = JSON.parse(fs.readFileSync(file, "utf8")).events;
    if (Array.isArray(events) && events.length) return events;
  } catch {}
  const full = await (await page.request.get(`${BASE}/api/generations/${g.id}`)).json();
  const seen = new Set();
  const out = [];
  for (const v of full.variants || []) for (const e of (v.agent && v.agent.events) || []) {
    const k = JSON.stringify([e.step, e.slide, e.variant, e.message]);
    if (!seen.has(k)) { seen.add(k); out.push(e); }
  }
  return out;
}

// The build screen at three moments (the agent designing, the critic, the layout), each in its own browser context: the
// «Создать презентацию» request and the job's stream are answered here from the recorded steps.
async function replayBuild(browser, W, H, tag, g, steps) {
  const stages = [
    ["4s", 0.12, (e) => e.step === "critic", []],
    ["20s", 0.33, (e) => e.step === "critic" && e.variant === (g.strategies || []).slice(-1)[0], []],
    ["45s", 0.62, () => false, [["structured: planned 6 slides, rendering", 0.5], ["structured: rendered slide 6/6", 0.55], ["structured: audit", 0.57], ["structured: done in 20.1s", 0.58], ["visual: planned 6 slides, rendering", 0.6], ["visual: rendered slide 3/6", 0.62]]],
  ];
  for (const [name, progress, stop, pipeline] of stages) {
    const jobId = `replay-${name}`;
    const cut = steps.findIndex(stop);
    const agent = steps.slice(0, cut < 0 ? steps.length : cut).map((e, i) => ({ job_id: jobId, status: "running", progress, message: e.message, t: i, type: "agent", step: e.step, slide: e.slide ?? null, variant: e.variant ?? null, seq: i + 1 }));
    const all = [...agent, ...pipeline.map(([message, p]) => ({ job_id: jobId, status: "running", progress: p, message, t: 0 }))];
    const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    await page.route("**/api/generations", (route) => (route.request().method() === "POST" ? route.fulfill({ json: { job_id: jobId, generation_id: g.id } }) : route.continue()));
    await page.route(`**/api/jobs/${jobId}/events`, (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: all.map((e) => `data: ${JSON.stringify({ ...e, progress })}\n\n`).join("") }));
    await page.route(`**/api/jobs/${jobId}`, (route) => route.fulfill({ json: { id: jobId, kind: "generate", status: "running", progress, message: all.length ? all[all.length - 1].message : "", error: null, created_at: 0, finished_at: null, result: null, agent } }));
    await page.goto(BASE + "/");
    await page.evaluate(() => { localStorage.removeItem("verstka.generation_id"); localStorage.removeItem("verstka.brief_draft"); });
    await page.reload();
    await page.waitForTimeout(1500);
    await page.locator("textarea").first().fill(g.brief || "Итоги пилота");
    await page.getByRole("button", { name: /Создать презентацию/ }).first().click().catch(() => console.log(`  ! no «Создать презентацию» on ${tag}`));
    await page.waitForTimeout(2500);
    await page.screenshot({ path: path.join(out, `${tag}-07-build-${name}.png`) });
    if (name === "45s") {
      await page.evaluate(() => { const m = document.querySelector("main"); if (m) m.scrollTop = m.scrollHeight; });
      await page.waitForTimeout(450);
      await page.screenshot({ path: path.join(out, `${tag}-07-build-${name}-end.png`) });
    }
    await ctx.close();
  }
}

async function latest(page, templateHint) {
  const gens = await (await page.request.get(`${BASE}/api/generations`)).json();
  const done = gens.filter((g) => g.status === "done" && (g.summary && Object.keys(g.summary).length));
  const pick = (hint) => done.find((g) => (g.template_file || "").includes(hint));
  return { short: pick("VK Tech"), long: pick("Education") || done[0] };
}

(async () => {
  const { chromium } = playwright();
  const browser = await chromium.launch({ channel: "chrome" });
  for (const [W, H] of sizes) {
    const tag = `${W}x${H}`;
    const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    const shot = async (name) => { await page.waitForTimeout(450); await page.screenshot({ path: path.join(out, `${tag}-${name}.png`) }); };
    const main = async (y) => { await page.evaluate((y) => { const m = document.querySelector("main"); if (m) m.scrollTop = y; }, y); };
    const mainHeight = async () => page.evaluate(() => { const m = document.querySelector("main"); return m ? [m.scrollHeight, m.clientHeight] : [0, 0]; });
    const scrollShots = async (name) => {
      const [sh, ch] = await mainHeight();
      let i = 0;
      for (let y = 0; y < sh; y += Math.max(200, ch - 120)) { await main(y); await shot(`${name}-${i++}`); if (y + ch >= sh) break; }
      await main(0);
    };
    const click = async (text, opts = {}) => {
      const loc = page.getByText(text, { exact: !!opts.exact }).first();
      await loc.click({ timeout: 4000 }).catch(() => console.log(`  ! no «${text}» on ${tag}`));
    };
    const esc = async () => { await page.keyboard.press("Escape"); await page.waitForTimeout(300); };
    const helper = async () => page.getByRole("button", { name: "Помощник", exact: true }).click().catch(() => console.log(`  ! no helper toggle on ${tag}`));
    const modalOpen = async () => page.evaluate(() => !!document.querySelector('[aria-modal="true"]'));

    const { short, long } = await latest(page);
    if (onlyBuild) {
      if (short) await replayBuild(browser, W, H, tag, short, await recordedSteps(page, short));
      else console.log(`  ! no finished short deck to replay on ${tag}`);
      await ctx.close();
      continue;
    }
    // --- create screen
    await page.goto(BASE + "/");
    await page.evaluate(() => { localStorage.removeItem("verstka.generation_id"); localStorage.removeItem("verstka.brief_draft"); });
    await page.reload();
    await page.waitForTimeout(1500);
    await scrollShots("01-create");
    await click("Настройки", { exact: true }); await page.waitForTimeout(450); await main(1e6); await shot("02-create-settings"); await click("Настройки", { exact: true }); await main(0);
    await click("Разбор шаблона", { exact: true }); await page.waitForTimeout(600); await shot("03-template-passport"); await esc();
    await click("Мои презентации", { exact: true }); await shot("04-history"); await esc();
    const brief = short ? short.brief : "Итоги пилота";
    await page.locator("textarea").first().fill(brief || "");
    await page.waitForTimeout(300);
    await scrollShots("05-create-filled");
    await helper(); await shot("06-helper-empty"); await esc();

    // --- build screen (optional): replayed from the recorded steps, or a real generation with --build=live
    if (build === "replay" && short) await replayBuild(browser, W, H, tag, short, await recordedSteps(page, short));
    if (build === "live" && short) {
      await page.getByRole("button", { name: "Создать презентацию" }).click();
      for (const t of [4, 20, 45]) { await page.waitForTimeout(t === 4 ? 4000 : (t === 20 ? 16000 : 25000)); await shot(`07-build-${t}s`); }
      await page.waitForFunction(() => !document.title.startsWith("Готовлю"), null, { timeout: 240000 }).catch(() => {});
    }

    // --- result screens
    for (const [key, g] of [[SHORT, short], [LONG, long]]) {
      if (!g) continue;
      await page.evaluate((id) => localStorage.setItem("verstka.generation_id", id), g.id);
      await page.goto(BASE + "/");
      await page.waitForTimeout(2500);
      await shot(`10-${key}-result-v1`);
      const variants = page.getByRole("radio");
      const n = await variants.count();
      for (let i = 1; i < n; i++) { await variants.nth(i).click(); await shot(`11-${key}-result-v${i + 1}`); }
      if (n) await variants.nth(0).click();
      await page.getByRole("button", { name: /Слайд 3:/ }).first().click().catch(() => {});
      await shot(`12-${key}-result-slide3`);
      if (key === SHORT) {
        await page.getByRole("button", { name: "На весь экран" }).click().catch(() => {});
        await shot(`13-${key}-lightbox`); await esc();
        // the drawer: opened once from the quality card, then every tab by its name
        await page.getByRole("button", { name: /^Качество:/ }).first().click({ timeout: 4000 }).catch(() => console.log(`  ! no quality card on ${tag}`));
        await page.waitForTimeout(500);
        const tabs = ["Качество", "Почему так", "Агент", "План", "Шаблон", "Файлы"];
        let k = 0;
        for (const t of tabs) {
          await page.getByRole("tab", { name: t, exact: true }).click({ timeout: 4000 }).catch(() => console.log(`  ! no tab «${t}» on ${tag}`));
          await page.waitForTimeout(500); await shot(`14-${key}-drawer-${k}`);
          const body = await page.evaluate(() => { const d = document.querySelector("[role=dialog] .overflow-y-auto, [role=dialog] [class*=overflow-y-auto]"); return d ? [d.scrollHeight, d.clientHeight] : [0, 0]; });
          if (body[0] > body[1] + 40) {
            await page.evaluate(() => { const d = document.querySelector("[role=dialog] .overflow-y-auto, [role=dialog] [class*=overflow-y-auto]"); if (d) d.scrollTop = d.scrollHeight; });
            await shot(`14-${key}-drawer-${k}-end`);
          }
          k++;
        }
        await esc();
        // the helper docked beside the result, then beside the drawer its answer opens
        await helper(); await page.waitForTimeout(400); await shot(`16-${key}-result-helper`);
        await page.getByRole("textbox", { name: /Сообщение/ }).fill("Как работал агент?").catch(() => console.log(`  ! no helper textbox on ${tag}`));
        await page.keyboard.press("Enter"); await page.waitForTimeout(2500); await shot(`17-${key}-drawer-helper`);
        if (await modalOpen()) await esc();
        await shot(`15-${key}-helper-chat`); await esc();
      }
    }
    await ctx.close();
  }
  await browser.close();
  console.log("done", out);
})().catch((e) => { console.error(e); process.exit(1); });
