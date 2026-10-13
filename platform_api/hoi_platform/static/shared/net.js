// HOI network helper, shared by the guest page and the staff app (classic script, strict CSP, no build step).
// Render's free servers sleep when idle; the first request then takes 30-60 s. HOINet.fetch(url, init) works like fetch()
// and adds two things:
//   1. "Waking up the server…": when a request has waited WAIT_MS and the server may be asleep (no answer yet on this page,
//      or none for SLEEP_MS), a small pill fades in at the top of the screen. It is fixed-position (no layout shift),
//      follows the page language (<html lang>), and goes away when the slow requests finish.
//   2. One retry: on a network error (GET / HEAD only, so an order is never sent twice) or a 502 / 503 / 504 from the
//      gateway (any method: the app never saw the request), it waits RETRY_MS and tries once more.
(() => {
  "use strict";
  const WAIT_MS = 4000, RETRY_MS = 1500, SLEEP_MS = 14 * 60 * 1000;  // ASSUMED: Render free sleeps after ~15 min idle
  const GATEWAY = [502, 503, 504];
  const TEXT = {
    en: "Waking up the server, this can take about 30 seconds…",
    hi: "सर्वर चालू हो रहा है, इसमें लगभग 30 सेकंड लग सकते हैं…",
  };
  const S = { lastOk: 0, slow: 0, el: null };

  function pill() {
    if (S.el) return S.el;
    const el = document.createElement("div");
    el.className = "waking";
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    el.innerHTML = '<i class="wspin" aria-hidden="true"></i><span></span>';
    document.body.appendChild(el);
    S.el = el;
    return el;
  }
  function paint() {
    if (!document.body) return;
    const el = pill();
    const lang = (document.documentElement.lang || "en").slice(0, 2);
    el.lastChild.textContent = TEXT[lang] || TEXT.en;
    el.classList.toggle("on", S.slow > 0);
  }
  const maybeAsleep = () => !S.lastOk || Date.now() - S.lastOk > SLEEP_MS;

  async function once(input, init) {
    const r = await fetch(input, init);
    if (r.status < 500 || !GATEWAY.includes(r.status)) S.lastOk = Date.now();
    return r;
  }

  async function wakeFetch(input, init) {
    const method = String((init && init.method) || "GET").toUpperCase();
    const asleep = maybeAsleep();
    let shown = false;
    const timer = asleep ? setTimeout(() => { shown = true; S.slow++; paint(); }, WAIT_MS) : null;
    try {
      let r;
      try { r = await once(input, init); }
      catch (e) {
        if (method !== "GET" && method !== "HEAD") throw e;
        await new Promise((res) => setTimeout(res, RETRY_MS));
        return await once(input, init);
      }
      if (GATEWAY.includes(r.status)) {
        await new Promise((res) => setTimeout(res, RETRY_MS));
        r = await once(input, init);
      }
      return r;
    } finally {
      clearTimeout(timer);
      if (shown) { S.slow = Math.max(0, S.slow - 1); paint(); }
    }
  }

  window.HOINet = { fetch: wakeFetch, text: TEXT };
})();
