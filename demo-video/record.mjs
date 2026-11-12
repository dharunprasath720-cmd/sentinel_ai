// Scripted, captioned screen recording of the SENTINEL dashboard.
//
//   BASE=http://127.0.0.1:8001 DEMO_HOME=<folder with .env.demo> FFMPEG=<ffmpeg.exe> node record.mjs
//
// Drives the real app in headless Chromium, records video, burns captions in as a page overlay, and
// then speeds up the dead waits (replay, AI report) and encodes an MP4. Nothing is narrated.
// Passwords are read from DEMO_HOME/.env.demo at run time and typed into a masked field; they are never logged.
import { chromium } from "playwright";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE ?? "http://127.0.0.1:8001";
const HOME = process.env.DEMO_HOME;
const FFMPEG = process.env.FFMPEG;
const OUT = path.resolve(process.env.OUT ?? "out");
const FAST = process.env.FAST === "1"; // shorter dwell times, for debugging the script
const RING_START = 2290;               // replay offset: just before the planted ring (stream position 2,299)
const LEGIT_ID = "SYN0013668";         // legitimate but unusual purchase (stream position 2,671)

if (!HOME || !FFMPEG) throw new Error("set DEMO_HOME (folder with .env.demo) and FFMPEG (path to ffmpeg)");
const envText = fs.readFileSync(path.join(HOME, ".env.demo"), "utf8");
const ANA_PASSWORD = envText.match(/^ANA_PASSWORD=(.+)$/m)?.[1]?.trim();
if (!ANA_PASSWORD) throw new Error("ANA_PASSWORD not found in .env.demo");

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(path.join(OUT, "frames"), { recursive: true });

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const SCALE = Number(process.env.SCALE ?? 0.68);   // caption dwell multiplier
const MAX_SECONDS = 175;                         // hackathon rule: the video must be under 3 minutes
const dwell = (ms) => (FAST ? Math.max(300, ms * 0.25) : ms * SCALE);

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1280, height: 720 },
  recordVideo: { dir: path.join(OUT, "raw"), size: { width: 1280, height: 720 } },
});

// Captions and a visible cursor live in the page so they are part of the recorded video.
await context.addInitScript(() => {
  const css = `
    #__caption{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);max-width:78%;z-index:2147483647;
      color:#fff;font:600 24px/1.35 Georgia,'Times New Roman',serif;text-align:center;pointer-events:none;
      text-shadow:0 0 3px #000,0 0 6px #000,0 2px 10px #000,0 0 18px rgba(0,0,0,.9);transition:opacity .25s;opacity:0}
    #__caption.on{opacity:1}
    #__cursor{position:fixed;width:24px;height:24px;margin:0;z-index:2147483646;background:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'><path d='M3 2l7.5 19 2.6-7.9L21 10.5z' fill='white' stroke='black' stroke-width='1.6' stroke-linejoin='round'/></svg>") no-repeat 0 0;
      pointer-events:none;transition:transform .08s;transform-origin:3px 2px;left:-40px;top:-40px}
    #__cursor.down{transform:scale(.85)}`;
  const build = () => {
    if (document.getElementById("__caption")) return;
    const st = document.createElement("style"); st.textContent = css; document.documentElement.appendChild(st);
    const c = document.createElement("div"); c.id = "__caption"; document.documentElement.appendChild(c);
    const k = document.createElement("div"); k.id = "__cursor"; document.documentElement.appendChild(k);
  };
  document.addEventListener("DOMContentLoaded", build);
  window.addEventListener("load", build);
  window.addEventListener("mousemove", (e) => { build(); const k = document.getElementById("__cursor"); k.style.left = e.clientX + "px"; k.style.top = e.clientY + "px"; }, true);
  window.addEventListener("mousedown", () => document.getElementById("__cursor")?.classList.add("down"), true);
  window.addEventListener("mouseup", () => document.getElementById("__cursor")?.classList.remove("down"), true);
  window.__caption = (text) => {
    build(); const c = document.getElementById("__caption");
    if (!text) { c.classList.remove("on"); return; }
    c.textContent = text; c.classList.add("on");
  };
});

const page = await context.newPage();
const t0 = Date.now();
const waits = []; // [startMs, endMs, speed] relative to the start of the video

const caption = (text) => page.evaluate((t) => window.__caption && window.__caption(t), text);
const say = async (text, ms) => { await caption(text); await page.waitForTimeout(dwell(ms)); };
const shot = (name) => page.screenshot({ path: path.join(OUT, "frames", `${name}.png`) });
async function fastForward(label, speed, fn) {
  const start = Date.now() - t0;
  try { return await fn(); } finally {
    const end = Date.now() - t0;
    if (end - start > 4000) waits.push([start, end, speed, label]);
    log(`wait "${label}": ${((end - start) / 1000).toFixed(0)} s real time, x${speed}`);
  }
}
async function click(locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error("no box to click");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: FAST ? 4 : 12 });
  await page.waitForTimeout(dwell(250));
  await locator.click();
  await page.waitForTimeout(dwell(300));
}
const top = () => page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
const card = async (title, lines, ms) => {
  await caption("");
  const html = `<!doctype html><meta charset=utf-8><body style="margin:0;height:100vh;display:grid;place-items:center;
    background:radial-gradient(circle at 70% 90%,#17305f,#0a1020 60%);color:#e8edf7;font-family:Georgia,serif;text-align:center">
    <div style="max-width:900px;padding:40px"><div style="font-size:64px;letter-spacing:.14em;font-weight:700">${title}</div>
    ${lines.map((l, i) => `<div style="margin-top:${i ? 18 : 26}px;font-size:${i ? 26 : 32}px;color:${i ? "#94a3c0" : "#6aa5ff"}">${l}</div>`).join("")}</div>`;
  await page.goto("data:text/html;charset=utf-8," + encodeURIComponent(html));
  await page.waitForTimeout(dwell(ms));
};

try {
  // ---------------------------------------------------------------- title
  await card("SENTINEL AI", ["Payment-fraud intelligence you can audit"], 4000);

  // ---------------------------------------------------------------- sign in
  log("scene: sign in");
  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  await page.locator(".login-card").waitFor();
  await say("Sign in as an analyst. Demo accounts are one click away; the password stays masked.", 3500);
  await click(page.locator(".chip", { hasText: "ana" }));
  await page.locator("#login-password").pressSequentially(ANA_PASSWORD, { delay: FAST ? 10 : 70 });
  await shot("01-login");
  await click(page.locator(".login-card button.btn-primary"));

  // ---------------------------------------------------------------- overview
  log("scene: overview");
  await page.locator(".tile-value").first().waitFor({ timeout: 60000 });
  await say("Overview: every payment is scored. These tiles count up from the live database.", 5500);
  await shot("02-overview");
  await page.locator('[aria-label="Risk level distribution"]').scrollIntoViewIfNeeded();
  await say("Log scale keeps small HIGH and CRITICAL groups visible next to thousands of LOW payments.", 4500);
  await say("Click a risk level to list its recent transactions.", 3500);
  await click(page.locator(".level-chip", { hasText: "MODERATE" }));
  await page.locator('[aria-label="Model quality"]').scrollIntoViewIfNeeded();
  await say("Model quality, honestly: recall sits beside precision. It misses things, and the screen says so.", 4500);
  await shot("03-model");
  await top();

  // ---------------------------------------------------------------- live monitoring
  log("scene: live monitoring");
  await click(page.locator(".nav a", { hasText: "Live Monitoring" }));
  await say("Live Monitoring replays held-back events through the real scoring pipeline.", 3500);
  await page.getByLabel(/speed/i).fill("1000");
  await page.getByLabel(/limit/i).fill("400");
  await page.getByLabel(/start at event/i).fill(String(RING_START));
  await say(`Starting at event ${RING_START}, just before a planted ring of coordinated accounts.`, 3500);
  await click(page.getByRole("button", { name: /start replay/i }));
  await say("Scored events stream into the grid. The first ring payments look ordinary on their own.", 7000);
  await shot("04-live-early");

  const firstHigh = await fastForward("waiting for the ring to be flagged", 6, async () => {
    await caption("Several ring accounts now share a device, and their scores climb (replay sped up).");
    await page.locator(".live-grid .ag-row.row-pulse a").first().waitFor({ timeout: 240000 });
    return page.locator(".live-grid .ag-row.row-pulse a").first().innerText();
  });
  log("first HIGH+ ring transaction:", firstHigh);
  await page.locator(".live-grid .ag-row.row-pulse").first().scrollIntoViewIfNeeded({ timeout: 2000 }).catch(() => {});
  await say("Ring rows turn HIGH, pulse, and are recommended Review. Nothing is blocked automatically.", 7000);
  await shot("05-live-high");

  // The grid renders only the rows on screen, so grab a row from inside the flagged cluster the moment one appears.
  const clusterRowId = () => page.evaluate(() => {
    for (const row of document.querySelectorAll(".live-grid .ag-row.row-pulse")) {
      const c = row.querySelector('[col-id="cluster"]')?.textContent?.trim();
      if (c && c !== "\u2014") return { id: row.querySelector("a")?.textContent ?? null, cluster: c };
    }
    return null;
  });
  await fastForward("waiting for the cluster to be flagged", 6, async () => {
    await caption("Enough accounts now share the device for the cluster to be flagged (replay sped up).");
    await page.waitForFunction(() => [...document.querySelectorAll(".live-grid .ag-row.row-pulse")].some((r) => {
      const c = r.querySelector('[col-id="cluster"]')?.textContent?.trim(); return !!c && c !== "\u2014"; }), null, { timeout: 150000 }).catch(() => {});
  });
  const found = await clusterRowId();
  const flaggedHigh = found?.id ?? null;
  log("flagged-cluster row:", found);
  if (found) {
    await page.locator(".live-grid .ag-row.row-pulse", { has: page.locator(`a:text-is("${found.id}")`) }).first().scrollIntoViewIfNeeded({ timeout: 2000 }).catch(() => {});
    await say("Cluster flagged: the Cluster column now names it. This is the shared-device pattern, caught as it forms.", 6500);
    await shot("05b-live-cluster");
  }

  // AG Grid: search while events keep streaming in; the filter holds and the counter updates
  const search = page.getByRole("searchbox", { name: /search events/i });
  await search.pressSequentially("CL_", { delay: FAST ? 10 : 90 });
  await say("The feed is an AG Grid table. Search or filter any column while events keep streaming in: the filter holds and the counter updates.", 7500);
  await shot("05c-live-filtered");
  await search.fill("");

  let sawLegit = false;
  await fastForward("waiting for the replay to finish", 14, async () => {
    await caption("The replay continues (sped up).");
    await page.getByText("Replay idle").first().waitFor({ timeout: 300000 }).catch(() => {});
  });
  await search.pressSequentially(LEGIT_ID, { delay: FAST ? 10 : 70 });
  const legitRow = page.locator(".live-grid .ag-row", { has: page.locator(`a:text-is("${LEGIT_ID}")`) });
  sawLegit = await legitRow.first().waitFor({ timeout: 10000 }).then(() => true).catch(() => false);
  if (sawLegit) {
    const text = (await legitRow.first().innerText()).replace(/\s+/g, " ");
    log("legit row:", text);
    await say(`Search finds the legitimate but unusual purchase: ${/MODERATE/.test(text) ? "rated MODERATE, action Monitor" : "rated as shown"}. Unusual is not fraud.`, 6000);
    await shot("06-live-legit");
  } else log("legit purchase not found; skipping its caption");
  await search.fill("");
  await page.getByRole("button", { name: /stop replay/i }).click().catch(() => {});
  const subject = flaggedHigh ?? firstHigh;
  log("investigation subject:", subject, flaggedHigh ? "(in a flagged cluster)" : "(no flagged-cluster row seen; using the first HIGH row)");

  // ---------------------------------------------------------------- graph
  log("scene: graph");
  await top();
  await click(page.locator(".nav a", { hasText: "Graph Explorer" }));
  await say("Graph Explorer: accounts, devices and merchants. Flagged clusters are listed, newest first.", 4000);
  const newest = page.locator('[aria-label="Flagged clusters"] button').first();
  log("newest flagged cluster:", (await newest.innerText()).replace(/\s+/g, " "));
  await click(newest);
  await page.locator(".react-flow__node").first().waitFor({ timeout: 60000 });
  log("graph nodes drawn:", await page.locator(".react-flow__node").count());
  await page.locator('[aria-label="Graph canvas"]').scrollIntoViewIfNeeded();
  await say("Border colour shows risk, and every node also says its level in words. Edges carry the transaction count.", 5000);
  await shot("07-graph");
  await click(page.locator(".react-flow__node", { hasText: "▲ account" }).first());
  await say("Click an account to pull in its neighbours. The explorer caps at 200 nodes and says when it cuts.", 5000);
  await shot("08-graph-expanded");

  // ---------------------------------------------------------------- investigation
  log("scene: investigation");
  await top();
  await page.keyboard.press("Control+k");
  await say("Ctrl+K jumps anywhere. Paste a transaction id to open its investigation.", 3000);
  await page.getByRole("combobox", { name: /search pages/i }).pressSequentially(subject, { delay: FAST ? 10 : 55 });
  await page.waitForTimeout(dwell(600));
  await page.keyboard.press("Enter");
  await page.getByRole("heading", { name: `Transaction ${subject}` }).waitFor({ timeout: 60000 });
  await page.locator('section[aria-label="Risk assessment"]').waitFor({ timeout: 60000 });
  await say("Risk factors, behaviour reasons, and the model's own explanation (SHAP) are all here.", 5500);
  await page.locator('section[aria-label="Model explanation"]').scrollIntoViewIfNeeded();
  await say("Each bar is a feature's contribution to the model's score. Contributions describe the model, not causes of fraud.", 6500);
  const riskText = (await page.locator("section[aria-label=\"Risk assessment\"]").innerText()).replace(/\s+/g, " ");
  const recommendedHold = /Hold recommended/i.test(riskText);
  log("risk panel for the subject:", riskText.slice(0, 120));
  await shot("09-investigation");
  await top();
  await page.locator(".alerts-grid").scrollIntoViewIfNeeded();
  await click(page.locator('.alerts-grid .ag-header-cell[col-id="level"]'));
  await click(page.locator('.alerts-grid .ag-header-cell[col-id="level"]'));
  await say("The alert list is an AG Grid triage table: sort by severity, filter, search, tick rows.", 4500);
  await page.getByRole("searchbox", { name: /search alerts/i }).pressSequentially(subject, { delay: FAST ? 10 : 70 });
  await page.waitForTimeout(dwell(500));
  await click(page.locator(".alerts-grid .ag-row .ag-selection-checkbox").first());
  await say("Tick the alerts to work, then open one case from the selection.", 3500);
  await shot("09b-triage");
  await click(page.getByRole("button", { name: /open case from \d+ selected/i }));
  await page.locator('section[aria-label="Case"]').waitFor({ timeout: 30000 });
  await say("Alerts become cases. Analysts add notes and decide.", 3500);
  await page.getByLabel(/new note/i).fill("Ring pattern: several accounts, one device, same merchants. Needs review.");
  await click(page.getByRole("button", { name: /add note/i }));
  await page.getByLabel(/action to approve/i).selectOption("HOLD_RECOMMENDED");
  await click(page.getByRole("button", { name: /approve action/i }));
  await say(recommendedHold
    ? "The system recommended a hold. The analyst approves it, and even then nothing is blocked automatically."
    : "The system recommended Review. Recording a hold is the analyst's own call, and it blocks nothing.", 5500);
  await shot("10-confirm");
  await click(page.getByRole("dialog").getByRole("button", { name: "Confirm" }));
  await page.waitForTimeout(dwell(1500));
  await shot("11-case");

  // AI report (real Claude call)
  const reportBtn = page.getByRole("button", { name: /generate ai report/i });
  await click(reportBtn);
  await fastForward("Claude writing the report", 10, async () => {
    await caption("Claude investigates through read-only tools. About a minute in real time (sped up).");
    await page.locator('section[aria-label="Investigation report"]').waitFor({ timeout: 240000 });
  });
  await page.locator('section[aria-label="Investigation report"]').scrollIntoViewIfNeeded();
  await say("Every claim cites an evidence id the tools returned. It says suspicious, never fraud confirmed.", 7000);
  await shot("12-report");
  await page.evaluate(() => document.querySelector('section[aria-label="Investigation report"]')?.scrollBy?.(0, 0));
  await page.evaluate(() => window.scrollBy({ top: 420, behavior: "instant" }));
  await say("It also lists the contradictory evidence, the limits of its confidence, and what is missing.", 6500);
  await shot("13-report-limits");

  // ---------------------------------------------------------------- the real PayPal Sandbox payment
  log("scene: paypal sandbox");
  await top();
  await page.getByLabel("Data source").selectOption("paypal_sandbox");
  await click(page.locator(".nav a", { hasText: "Live Monitoring" }));
  const ppRow = page.locator(".live-grid .ag-row", { has: page.locator('a:text-matches("^PP-")') }).first();
  const hasPayPal = await ppRow.waitFor({ timeout: 15000 }).then(() => true).catch(() => false);
  if (hasPayPal) {
    await ppRow.scrollIntoViewIfNeeded({ timeout: 2000 }).catch(() => {});
    const ppText = (await ppRow.innerText()).replace(/\s+/g, " ");
    log("paypal row:", ppText);
    await say("Data source: PayPal Sandbox. A real Sandbox payment, delivered by signed webhook and verified with PayPal before scoring (received 11 Nov 2026).", 7500);
    await shot("15-paypal-live");
    await click(ppRow.locator("a").first());
    await page.getByRole("heading", { name: /^Transaction PP-/ }).waitFor({ timeout: 60000 });
    await say("The webhook carries no payer identity, so it is scored as its own account: low risk, action Allow. Sources are never blended.", 7000);
    await shot("16-paypal-detail");
  } else {
    log("no PayPal row in this demo; showing a card instead");
    await card("PayPal Sandbox", ["A real signed payment webhook was verified in testing", "Not shown in this recording."], 5000);
  }
  await card("SENTINEL AI", ["Deterministic scoring. An AI that must show its evidence. A human who decides.",
    "About a fifth of planted fraud is missed. The data is synthetic. PayPal is Sandbox only; refunds were never run."], 7000);
} catch (err) {
  log("FAILED:", err.message);
  await shot("zz-failure").catch(() => {});
  await context.close();
  await browser.close();
  process.exit(1);
}

const videoPath = await page.video().path();
await context.close();
await browser.close();
const raw = path.join(OUT, "demo-raw.webm");
fs.renameSync(videoPath, raw);
fs.writeFileSync(path.join(OUT, "waits.json"), JSON.stringify(waits, null, 2));
log("raw video:", raw, "| fast-forward segments:", waits.length);

// ---------------------------------------------------------------- speed up the waits, encode MP4
const probe = spawnSync(FFMPEG, ["-i", raw], { encoding: "utf8" });
const dur = probe.stderr.match(/Duration: (\d+):(\d+):([\d.]+)/);
const total = dur ? (+dur[1] * 3600 + +dur[2] * 60 + parseFloat(dur[3])) : null;
if (!total) throw new Error("could not read the video duration");
const segs = []; let cursor = 0;
for (const [s, e, speed] of waits.sort((a, b) => a[0] - b[0])) {
  const a = Math.max(cursor, s / 1000), b = Math.min(total, e / 1000);
  if (a > cursor) segs.push([cursor, a, 1]);
  if (b > a) segs.push([a, b, speed]);
  cursor = Math.max(cursor, b);
}
if (cursor < total) segs.push([cursor, total, 1]);
const filter = segs.map(([a, b, sp], i) => `[0:v]trim=start=${a.toFixed(3)}:end=${b.toFixed(3)},setpts=(PTS-STARTPTS)/${sp}[v${i}]`).join(";")
  + ";" + segs.map((_, i) => `[v${i}]`).join("") + `concat=n=${segs.length}:v=1:a=0[out]`;
const mp4 = path.join(OUT, "sentinel-demo.mp4");
const enc = spawnSync(FFMPEG, ["-y", "-i", raw, "-filter_complex", filter, "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
  "-crf", "20", "-preset", "medium", "-r", "30", "-movflags", "+faststart", mp4], { encoding: "utf8" });
if (enc.status !== 0) { console.error(enc.stderr.slice(-1500)); throw new Error("ffmpeg failed"); }
const outProbe = spawnSync(FFMPEG, ["-i", mp4], { encoding: "utf8" });
const od = outProbe.stderr.match(/Duration: (\d+):(\d+):([\d.]+)/);
const seconds = od ? +od[1] * 3600 + +od[2] * 60 + parseFloat(od[3]) : NaN;
log("MP4:", mp4, "| length", seconds.toFixed(1), "s");
if (!(seconds < MAX_SECONDS)) { console.error(`TOO LONG: ${seconds.toFixed(1)} s (limit ${MAX_SECONDS} s). Lower SCALE and record again.`); process.exit(2); }
