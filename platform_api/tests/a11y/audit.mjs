// Accessibility audit (WCAG 2.1 A/AA rules of axe-core) of pages served by a running platform API, in headless
// Chrome/Edge at a phone size (390 x 844), plus a touch-target check (visible controls smaller than 44 x 44 CSS px).
//
//   node audit.mjs <base-url> <scenario> [<scenario> ...]      scenarios: guest:<room token>, worker-login, worker-demo
//
// Prints one JSON object: { "<page>": { "violations": [{id, impact, help, nodes, targets}], "small_targets": [...] } }.
// Needs Node 22+ (built-in WebSocket) and a Chrome or Edge binary (CHROME_PATH, or the usual install paths).
// SHOT_DIR=<folder> also saves a phone-size screenshot of every audited page (for the docs).
import { spawn } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";

const require = createRequire(import.meta.url);
const AXE = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const [base, ...scenarios] = process.argv.slice(2);
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const MIN_TARGET = 44; // WCAG 2.5.5 (AAA) and Apple / Android guidance: guests and staff use phones

function browserPath() {
  const candidates = [
    process.env.CHROME_PATH,
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ];
  return candidates.find((p) => p && existsSync(p));
}

function launch(bin) {
  return new Promise((resolve, reject) => {
    const args = [
      "--headless=new", "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check", "--disable-gpu",
      "--no-sandbox", `--user-data-dir=${join(tmpdir(), `hoi-a11y-${process.pid}`)}`, "about:blank",
    ];
    const proc = spawn(bin, args, { stdio: ["ignore", "ignore", "pipe"] });
    let buf = "";
    proc.stderr.on("data", (d) => {
      buf += d;
      const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
      if (m) resolve({ proc, ws: m[1] });
    });
    proc.on("exit", (c) => reject(new Error(`browser exited (${c}): ${buf.slice(-400)}`)));
    setTimeout(() => reject(new Error("browser did not start")), 20000);
  });
}

// A minimal Chrome DevTools Protocol client over the browser websocket (flat sessions).
function cdp(url) {
  const ws = new WebSocket(url);
  let id = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (!msg.id || !pending.has(msg.id)) return;
    const { res, rej } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) rej(new Error(msg.error.message));
    else res(msg.result);
  };
  const send = (method, params = {}, sessionId) =>
    new Promise((res, rej) => {
      const n = ++id;
      pending.set(n, { res, rej });
      ws.send(JSON.stringify({ id: n, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  return new Promise((resolve) => {
    ws.onopen = () => resolve({ send, close: () => ws.close() });
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function openPage(c) {
  const { targetId } = await c.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await c.send("Target.attachToTarget", { targetId, flatten: true });
  const s = (m, p) => c.send(m, p, sessionId);
  await s("Page.enable");
  await s("Runtime.enable");
  await s("Page.setBypassCSP", { enabled: true }); // lets the audit inject axe; the page itself is served unchanged
  await s("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  const evaluate = async (expression) => {
    const r = await s("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  const waitFor = async (cond, ms = 30000) => {
    for (const t0 = Date.now(); Date.now() - t0 < ms; await sleep(200)) if (await evaluate(`!!(${cond})`)) return;
    throw new Error("timed out waiting for " + cond);
  };
  const go = async (url) => {
    await s("Page.navigate", { url });
    await sleep(300);
    await waitFor("document.readyState === 'complete'");
    await sleep(1200);
  };
  const shot = async (name) => {
    if (!process.env.SHOT_DIR) return;
    const { data } = await s("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(process.env.SHOT_DIR, name.replace(/[^a-z0-9]+/gi, "-").replace(/-$/, "") + ".png"), Buffer.from(data, "base64"));
  };
  return { evaluate, waitFor, go, shot, close: () => c.send("Target.closeTarget", { targetId }) };
}

async function audit(p, name) {
  await p.shot(name);
  await p.evaluate(AXE + ";true");
  const violations = await p.evaluate(`axe.run(document, { runOnly: { type: "tag", values: ${JSON.stringify(TAGS)} }, resultTypes: ["violations"] })
    .then((r) => r.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length,
      targets: v.nodes.slice(0, 6).map((n) => n.target.join(" ")) })))`);
  // visible controls whose tappable box (the control, or the label wrapping a checkbox) is under 44 x 44
  const small = await p.evaluate(`[...document.querySelectorAll("button, a[href], input, select, textarea, [role=button]")]
    .filter((el) => { const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && el.type !== "hidden"; })
    .filter((el) => { const box = (el.matches("input[type=checkbox], input[type=radio]") && el.closest("label")) || el;
      const r = box.getBoundingClientRect(); return r.width < ${MIN_TARGET} - 0.5 || r.height < ${MIN_TARGET} - 0.5; })
    .map((el) => { const r = el.getBoundingClientRect();
      const name = el.id ? "#" + el.id : el.tagName.toLowerCase() + (el.classList[0] ? "." + el.classList[0] : "") + (el.dataset.lang ? "[" + el.dataset.lang + "]" : "");
      return name + " " + Math.round(r.width) + "x" + Math.round(r.height); })`);
  // language of parts (WCAG 3.1.2): visible Devanagari text inside an element whose language is English is read
  // with an English voice; it needs lang="hi" (axe only validates lang values, it does not check this)
  const wrongLang = await p.evaluate(`(() => { const out = [], w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const el = n.parentElement; if (!/[\u0900-\u097F]/.test(n.textContent) || !el || !el.getClientRects().length) continue;
      const lang = (el.closest("[lang]") || document.documentElement).lang || "";
      if (!lang.startsWith("hi")) out.push(n.textContent.trim().slice(0, 30));
    } return out; })()`);
  return { violations, small_targets: [...new Set(small)], wrong_lang: wrongLang };
}

async function main() {
  const bin = browserPath();
  if (!bin) {
    console.error("no Chrome/Edge found (set CHROME_PATH)");
    process.exit(2);
  }
  const { proc, ws } = await launch(bin);
  const c = await cdp(ws);
  const out = {};
  try {
    for (const sc of scenarios) {
      const p = await openPage(c);
      if (sc.startsWith("guest:")) {
        await p.go(`${base}/guest/?t=${encodeURIComponent(sc.slice(6))}`);
        await p.waitFor("document.querySelector('#menu .opt')");
        for (const tab of ["ask", "explore", "requests", "checkout"]) {
          await p.evaluate(`document.querySelector('[data-tab="${tab}"]').click(); true`);
          await sleep(800);
          out[`guest/${tab}`] = await audit(p, `guest-${tab}`);
        }
        await p.evaluate(`document.querySelector('[data-lang="hi"]').click(); document.querySelector('[data-tab="explore"]').click(); true`);
        await sleep(800);
        out["guest/explore (Hindi)"] = await audit(p, "guest-explore-hindi");
        // status message (WCAG 4.1.3): after a request is sent, the confirmation must be in the role=status region
        await p.evaluate(`document.querySelector('[data-lang="en"]').click(); document.querySelector('[data-tab="ask"]').click(); true`);
        await sleep(500);
        await p.evaluate(`document.querySelector('#menu .opt[data-key="towels"]').click(); true`);
        await sleep(2500);
        out["guest/request sent"] = { announced: await p.evaluate(`(document.querySelector('[role=status]#live') || {}).textContent || ""`) };
      } else if (sc === "worker-login") {
        await p.go(`${base}/worker/`);
        await p.waitFor("document.querySelector('#user') && document.querySelector('#user').offsetParent");
        out["worker/sign-in"] = await audit(p, "worker-sign-in");
      } else if (sc === "worker-demo") {
        await p.go(`${base}/worker/`);
        await p.waitFor("document.querySelector('#demoBtn') && !document.querySelector('#demoBtn').classList.contains('hidden')");
        await p.evaluate("document.querySelector('#demoBtn').click(); true");
        await p.waitFor("!document.querySelector('#user') || !document.querySelector('#user').offsetParent");
        await sleep(2000);
        for (const tab of ["today", "jobs", "supplies", "me"]) {
          await p.evaluate(`document.querySelector('[data-tab="${tab}"]').click(); true`);
          await sleep(900);
          out[`worker/${tab}`] = await audit(p, `worker-${tab}`);
        }
      }
      await p.close();
    }
  } finally {
    c.close();
    proc.kill();
  }
  console.log(JSON.stringify(out, null, 1));
}

main().catch((e) => {
  console.error(e.stack || String(e));
  process.exit(1);
});
