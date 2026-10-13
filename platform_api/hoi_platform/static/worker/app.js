// HOI staff app. Plain JS, no build step, strict CSP (no inline scripts). Talks only to the platform API on the same origin.
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const DAYS = { en: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"], hi: ["रवि", "सोम", "मंगल", "बुध", "गुरु", "शुक्र", "शनि"] };
  const DEPTS = {
    en: { housekeeping: "Housekeeping", fnb_service: "F&B service", kitchen: "Kitchen", front_office: "Front office", maintenance: "Maintenance", security: "Security" },
    hi: { housekeeping: "हाउसकीपिंग", fnb_service: "एफ़&बी सर्विस", kitchen: "किचन", front_office: "फ़्रंट ऑफ़िस", maintenance: "मेंटेनेंस", security: "सिक्योरिटी" },
  };
  const SHIFTS = { en: { morning: "Morning", evening: "Evening", night: "Night" }, hi: { morning: "सुबह की", evening: "शाम की", night: "रात की" } };
  const day = (i) => (DAYS[S.lang] || DAYS.en)[i];
  const dept = (k) => (DEPTS[S.lang] || DEPTS.en)[k] || k || "";
  const shiftName = (k) => (SHIFTS[S.lang] || SHIFTS.en)[k] || k;
  // Local calendar date as YYYY-MM-DD. Converting through UTC would shift Indian (UTC+5:30) dates back by one day.
  const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

  // ---------------------------------------------------------------- state
  const S = { access: null, refresh: null, remember: true, user: null, tenant: null, me: null, lang: localStorage.getItem("hoi.lang") || "en",
              tab: "today", jobs: [], items: [], basket: {}, lastOfferId: null, poll: null, cam: null };
  const t = (k) => (window.HOI_I18N[S.lang] || window.HOI_I18N.en)[k] || window.HOI_I18N.en[k] || k;

  function store() { return S.remember ? localStorage : sessionStorage; }
  function saveRefresh(tok) { S.refresh = tok; localStorage.removeItem("hoi.rt"); sessionStorage.removeItem("hoi.rt"); if (tok) store().setItem("hoi.rt", tok); }

  // ---------------------------------------------------------------- api
  async function api(method, path, body, isForm) {
    const opts = { method, headers: {} };
    if (S.access) opts.headers.Authorization = "Bearer " + S.access;
    if (body !== undefined) {
      if (isForm) opts.body = body; else { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    }
    let r;
    try { r = await fetch(path, opts); } catch (e) { throw new Error(t("offline")); }
    if (r.status === 401 && S.refresh && path !== "/auth/refresh") {
      if (await refresh()) return api(method, path, body, isForm);
      signOut(true); throw new Error(t("session_expired"));
    }
    if (!r.ok) {
      let msg = t("wrong");
      try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : msg; } catch (e) { /* not json */ }
      throw new Error(msg);
    }
    if (r.status === 204) return null;
    const ct = r.headers.get("content-type") || "";
    return ct.includes("json") ? r.json() : r.blob();
  }

  async function refresh() {
    try {
      const r = await fetch("/auth/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: S.refresh }) });
      if (!r.ok) return false;
      const j = await r.json();
      S.access = j.token; saveRefresh(j.refresh_token); S.user = j.user; S.tenant = j.tenant;
      return true;
    } catch (e) { return false; }
  }

  function toast(msg) {
    const el = document.createElement("div"); el.className = "toast"; el.textContent = msg; document.body.appendChild(el);
    setTimeout(() => el.remove(), 2600);
  }

  // ---------------------------------------------------------------- i18n
  function applyLang() {
    document.documentElement.lang = S.lang;
    $$("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    $$("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
    $$("[data-lang]").forEach((b) => b.classList.toggle("on", b.dataset.lang === S.lang));
    renderVoiceChips();
    if (typeof fillVoices === "function" && V) fillVoices();
    if (S.user) renderAll();
  }
  $$("[data-lang]").forEach((b) => b.addEventListener("click", () => { S.lang = b.dataset.lang; localStorage.setItem("hoi.lang", S.lang); applyLang(); }));

  // ---------------------------------------------------------------- auth
  async function signIn(sess) {
    if (sess.user.role !== "worker") { $("#loginErr").textContent = "This app is for employees. Managers use the HOI dashboard."; $("#loginErr").classList.remove("hidden"); return; }
    S.access = sess.token; saveRefresh(sess.refresh_token); S.user = sess.user; S.tenant = sess.tenant;
    await boot();
  }

  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("#loginErr").classList.add("hidden");
    S.remember = $("#remember").checked;
    try { await signIn(await api("POST", "/auth/login", { username: $("#user").value.trim(), password: $("#pin").value })); }
    catch (err) { $("#loginErr").textContent = err.message; $("#loginErr").classList.remove("hidden"); }
  });
  $("#demoBtn").addEventListener("click", async () => {
    try { S.remember = $("#remember").checked; await signIn(await api("POST", "/auth/demo/E134")); }
    catch (err) { $("#loginErr").textContent = err.message; $("#loginErr").classList.remove("hidden"); }
  });

  async function signOut(silent) {
    clearInterval(S.poll);
    closeVoice();
    if (S.refresh && !silent) { try { await api("POST", "/auth/logout", { refresh_token: S.refresh }); } catch (e) { /* ignore */ } }
    S.access = null; S.user = null; saveRefresh(null);
    $("#app").classList.add("hidden"); $("#login").classList.remove("hidden");
  }
  $("#signout").addEventListener("click", () => signOut(false));

  // ---------------------------------------------------------------- boot
  async function boot() {
    $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
    try { S.me = await api("GET", "/me/shifts"); } catch (e) { S.me = { shifts: [], department: null }; }
    try { S.items = await api("GET", "/inventory/items"); } catch (e) { S.items = []; }
    renderAll();
    await pollJobs();
    clearInterval(S.poll);
    S.poll = setInterval(pollJobs, 2000);
  }

  function renderAll() {
    const emp = S.user.employee_id || S.user.username;
    $("#avatar").textContent = emp.slice(-3);
    $("#whoName").textContent = emp;
    $("#whoDept").textContent = dept(S.me?.department);
    $("#shiftChip").textContent = S.me?.on_shift_now ? t("on_shift") : t("off_shift");
    $("#meId").textContent = emp; $("#meDept").textContent = dept(S.me?.department) || "—"; $("#meHotel").textContent = S.tenant?.name || "";
    if (S.tenant?.brand_color) document.documentElement.style.setProperty("--brand", S.tenant.brand_color);
    renderToday(); renderJobs(); renderItems(); loadRequests();
  }

  // ---------------------------------------------------------------- tabs
  function show(tab) {
    S.tab = tab;
    $$(".tab").forEach((el) => el.classList.toggle("hidden", el.id !== "tab-" + tab));
    $$(".tabbar button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
    $("#voiceFab").classList.toggle("hidden", !["today", "jobs"].includes(tab));
    if (tab === "supplies") loadRequests();
    window.scrollTo({ top: 0 });
  }
  $$(".tabbar button").forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));
  $$("[data-goto]").forEach((b) => b.addEventListener("click", () => show(b.dataset.goto)));

  // ---------------------------------------------------------------- today
  function renderToday() {
    const shifts = S.me?.shifts || [];
    const curDay = S.me?.current_shift?.day;
    const today = shifts.find((s) => s.date === curDay);
    const hero = $("#todayHero");
    if (today) {
      hero.className = "todayhero anim";
      hero.innerHTML = `<div class="eyebrow">${esc(t("today"))} · ${esc(fmtDay(today.date))}</div><h2>${esc(shiftName(today.shift))} ${esc(t("today_shift"))}</h2>` +
        `<div>${esc(today.hours)} ${esc(t("hours"))} · ${esc(dept(S.me.department))}</div>`;
    } else {
      hero.className = "todayhero off anim";
      hero.innerHTML = `<div class="eyebrow">${esc(t("today"))}</div><h2>${esc(t("day_off"))}</h2><div>${esc(t("rest"))}</div>`;
    }
    const wk = $("#week");
    if (!shifts.length && !S.me?.week_start) { wk.innerHTML = ""; $("#weekNote").textContent = t("no_roster"); return; }
    const start = S.me.week_start ? new Date(S.me.week_start + "T00:00:00") : new Date();
    const by = Object.fromEntries(shifts.map((s) => [s.date, s]));
    let html = "";
    for (let i = 0; i < 7; i++) {
      const d = new Date(start); d.setDate(start.getDate() + i);
      const iso = ymd(d), s = by[iso];
      html += `<div class="day ${iso === curDay ? "on" : ""} ${s ? "work" : ""}"><b>${d.getDate()}</b><span>${day(d.getDay())}</span><span class="s">${s ? esc(shiftName(s.shift).slice(0, S.lang === "hi" ? 4 : 3)) : esc(t("off"))}</span></div>`;
    }
    wk.innerHTML = html;
    const hrs = shifts.reduce((a, s) => a + (s.hours || 0), 0);
    $("#weekNote").textContent = `${shifts.length} ${t("shifts_week")} · ${hrs} ${t("hours")}`;
  }
  const fmtDay = (iso) => { const d = new Date(iso + "T00:00:00"); return `${day(d.getDay())} ${d.getDate()}`; };

  // ---------------------------------------------------------------- jobs
  async function pollJobs() {
    if (!S.access) return;
    try { S.jobs = await api("GET", "/dispatch/jobs"); } catch (e) { return; }
    const offer = S.jobs.find((j) => j.status === "offered" && j.offer_to === (S.user.employee_id || S.user.username));
    if (offer && offer.id !== S.lastOfferId) {
      S.lastOfferId = offer.id;
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
      if (S.tab !== "jobs") toast(t("new_request") + ": " + offer.title);
    }
    if (!offer) S.lastOfferId = null;
    $("#jobDot").classList.toggle("hidden", !offer);
    $("#tJobs").textContent = S.jobs.filter((j) => j.status !== "done").length;
    renderJobs();
  }

  function renderJobs() {
    const me = S.user.employee_id || S.user.username;
    const offer = S.jobs.find((j) => j.status === "offered" && j.offer_to === me);
    const active = S.jobs.filter((j) => ["accepted", "in_progress"].includes(j.status) && j.assigned_to === me);
    const done = S.jobs.filter((j) => j.status === "done" && j.assigned_to === me).slice(0, 5);
    const oEl = $("#offer");
    if (offer) {
      const left = offer.seconds_left || 0, total = Math.max(left, 30);
      oEl.innerHTML = `<div class="offer anim"><div class="ring" aria-live="polite">${left}</div><div class="t">${esc(t("new_request"))}</div>` +
        `<h2>${esc(offer.title)}</h2><div class="muted">${offer.room ? esc(t("room")) + " " + esc(offer.room) + " · " : ""}${esc(t("urgency_" + offer.urgency))}</div>` +
        `<div class="bar"><i data-w="${Math.round((100 * left) / total)}"></i></div>` +
        `<div class="row"><button class="btn" data-act="decline" data-id="${esc(offer.id)}">${esc(t("decline"))}</button>` +
        `<button class="btn primary" data-act="accept" data-id="${esc(offer.id)}">${esc(t("accept"))}</button></div></div>`;
      oEl.querySelectorAll("[data-w]").forEach((i) => { i.style.width = i.dataset.w + "%"; });
    } else oEl.innerHTML = "";
    $("#active").innerHTML = active.map((j) => {
      const step = j.status === "accepted" ? 1 : 2;
      return `<div class="job anim"><div class="row"><h3>${esc(j.title)}</h3><span class="chip ${step === 1 ? "watch" : "low"}">${esc(t(j.status))}</span></div>` +
        `<div class="muted">${j.room ? esc(t("room")) + " " + esc(j.room) : ""}</div><div class="steps"><span class="on"></span><span class="${step === 2 ? "on" : ""}"></span><span></span></div>` +
        `<button class="btn primary" data-act="photo" data-kind="${step === 1 ? "before" : "after"}" data-id="${esc(j.id)}">📷 ${esc(t(step === 1 ? "before_photo" : "after_photo"))}</button></div>`;
    }).join("");
    $("#noJobs").classList.toggle("hidden", !!offer || active.length > 0);
    $("#doneList").innerHTML = done.length ? `<h3>${esc(t("completed_recent"))}</h3>` + done.map((j) =>
      `<div class="req"><div class="row"><b>${esc(j.title)}</b><span class="chip low">${esc(t("done"))}</span></div>` +
      `<div class="muted">${esc((j.done_at || "").slice(11, 16))}</div></div>`).join("") : "";
  }

  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const id = b.dataset.id;
    b.disabled = true;
    try {
      if (b.dataset.act === "accept") { await api("POST", `/dispatch/jobs/${encodeURIComponent(id)}/accept`, {}); }
      else if (b.dataset.act === "decline") { await api("POST", `/dispatch/jobs/${encodeURIComponent(id)}/decline`, {}); }
      else if (b.dataset.act === "photo") { openCamera(id, b.dataset.kind); }
      await pollJobs();
    } catch (err) { toast(err.message.includes("no longer") ? t("gone") : err.message); await pollJobs(); }
    finally { b.disabled = false; }
  });

  // ---------------------------------------------------------------- camera (live only, no gallery)
  async function openCamera(jobId, kind) {
    if (S.cam?.stream) S.cam.stream.getTracks().forEach((tr) => tr.stop());
    S.cam = { jobId, kind, blob: null, stream: null };
    $("#camRetry").classList.add("hidden");
    $("#camTitle").textContent = t(kind === "before" ? "before_photo" : "after_photo");
    $("#camErr").classList.add("hidden"); $("#preview").classList.add("hidden"); $("#video").classList.remove("hidden");
    $("#camShoot").classList.remove("hidden"); $("#camConfirm").classList.add("hidden");
    $("#camera").classList.remove("hidden");
    try {
      S.cam.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } }, audio: false });
      $("#video").srcObject = S.cam.stream;
    } catch (err) {
      $("#camErr").textContent = t("camera_denied"); $("#camErr").classList.remove("hidden");
      $("#camShoot").classList.add("hidden"); $("#camRetry").classList.remove("hidden");
    }
  }
  function closeCamera() {
    if (S.cam?.stream) S.cam.stream.getTracks().forEach((tr) => tr.stop());
    $("#video").srcObject = null; $("#camRetry").classList.add("hidden");
    $("#camera").classList.add("hidden"); S.cam = null;
  }
  $("#camClose").addEventListener("click", closeCamera);
  $("#camRetry").addEventListener("click", () => { const { jobId, kind } = S.cam; closeCamera(); openCamera(jobId, kind); });
  $("#snap").addEventListener("click", () => {
    const v = $("#video"), c = $("#canvas");
    c.width = v.videoWidth || 960; c.height = v.videoHeight || 1280;
    c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
    c.toBlob((blob) => {
      S.cam.blob = blob;
      $("#preview").src = URL.createObjectURL(blob); $("#preview").classList.remove("hidden"); $("#video").classList.add("hidden");
      $("#camShoot").classList.add("hidden"); $("#camConfirm").classList.remove("hidden");
    }, "image/jpeg", 0.85);
  });
  $("#retake").addEventListener("click", () => {
    $("#preview").classList.add("hidden"); $("#video").classList.remove("hidden");
    $("#camShoot").classList.remove("hidden"); $("#camConfirm").classList.add("hidden");
  });
  $("#usePhoto").addEventListener("click", async () => {
    const { jobId, kind, blob } = S.cam;
    $("#usePhoto").disabled = true;
    try {
      const fd = new FormData(); fd.append("kind", kind); fd.append("file", blob, `${kind}.jpg`);
      await api("POST", `/dispatch/jobs/${encodeURIComponent(jobId)}/photos`, fd, true);
      await api("POST", `/dispatch/jobs/${encodeURIComponent(jobId)}/${kind === "before" ? "start" : "complete"}`, {});
      closeCamera(); toast(t(kind === "before" ? "started" : "job_done")); await pollJobs();
    } catch (err) { $("#camErr").textContent = err.message; $("#camErr").classList.remove("hidden"); }
    finally { $("#usePhoto").disabled = false; }
  });

  // ---------------------------------------------------------------- supplies
  function renderItems() {
    const q = ($("#itemSearch").value || "").toLowerCase();
    const dept = S.me?.department;
    const list = S.items.filter((i) => (!dept || !i.department || i.department === dept) && (!q || i.name.toLowerCase().includes(q))).slice(0, 40);
    $("#items").innerHTML = list.map((i) =>
      `<div class="item"><div class="name">${esc(i.name)}<small>${esc(i.unit)}</small></div><div class="stepper">` +
      `<button type="button" data-step="-1" data-item="${esc(i.id)}" aria-label="less">−</button><b>${S.basket[i.id] || 0}</b>` +
      `<button type="button" data-step="1" data-item="${esc(i.id)}" aria-label="more">+</button></div></div>`).join("");
    $("#sendReq").disabled = !Object.values(S.basket).some((v) => v > 0);
  }
  $("#itemSearch").addEventListener("input", renderItems);
  $("#items").addEventListener("click", (e) => {
    const b = e.target.closest("[data-step]"); if (!b) return;
    const id = b.dataset.item; S.basket[id] = Math.max(0, (S.basket[id] || 0) + Number(b.dataset.step));
    renderItems();
  });
  $("#sendReq").addEventListener("click", async () => {
    const lines = Object.fromEntries(Object.entries(S.basket).filter(([, v]) => v > 0));
    $("#sendReq").disabled = true;
    try {
      await api("POST", "/inventory/requests", { department: S.me?.department || "housekeeping", lines, room: $("#room").value.trim() || null, note: "" });
      S.basket = {}; $("#room").value = ""; renderItems(); toast(t("sent")); loadRequests();
    } catch (err) { toast(err.message); $("#sendReq").disabled = false; }
  });
  async function loadRequests() {
    let reqs = [];
    try { reqs = await api("GET", "/inventory/requests"); } catch (e) { return; }
    $("#tReqs").textContent = reqs.filter((r) => ["pending", "partial"].includes(r.status)).length;
    const name = Object.fromEntries(S.items.map((i) => [i.id, i.name]));
    const tone = { pending: "watch", partial: "watch", issued: "low", rejected: "high" };
    $("#reqs").innerHTML = reqs.slice(0, 15).map((r) =>
      `<div class="req"><div class="row"><b>${r.lines.map((l) => esc(name[l.item_id] || "?") + " " + l.qty_issued + "/" + l.qty).join(", ")}</b>` +
      `<span class="chip ${tone[r.status] || "gray"}">${esc(t(r.status))}</span></div>` +
      `<div class="muted">${esc(r.created_at.slice(0, 16).replace("T", " "))}${r.room ? " · " + esc(t("room")) + " " + esc(r.room) : ""}</div></div>`).join("");
  }

  // ---------------------------------------------------------------- voice assistant (/me/voice/*)
  // Speech -> /me/voice/transcribe (cloud STT, after consent) -> /me/voice/command (rules) -> spoken reply + confirm card.
  // Nothing changes until Confirm (-> /me/voice/act). "Done" always goes through the after-photo (live camera flow).
  const local = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };
  const V = { rec: null, consent: local.get("hoi.voice_consent") === "1", action: null };
  function renderVoiceChips() {
    const chips = t("voice_chips");
    $("#vChips").innerHTML = (Array.isArray(chips) ? chips : []).map((c) => `<button type="button" data-vchip="${esc(c)}">${esc(c)}</button>`).join("");
  }
  function vState(text) { $("#vState").textContent = text || ""; }
  function vLog(text, who) {
    const el = document.createElement("div"); el.className = "vmsg " + who; el.textContent = text;
    $("#vLog").appendChild(el); el.scrollIntoView({ block: "end" });
  }
  // Spoken replies: /shared/voice.js (server voice when configured; a 204 means the browser voice speaks).
  async function serverVoice(text, lang) { const b = await api("POST", "/me/voice/tts", { text, lang }); return b instanceof Blob ? b : null; }
  function vSpeak(text, lang) { if (window.HOIVoice) window.HOIVoice.speak(text, lang || S.lang, { server: serverVoice }).catch(() => {}); }
  async function fillVoices() {
    if (!window.HOIVoice) return;
    const n = await window.HOIVoice.fillPicker($("#voicePick"), S.lang);
    $("#voiceCard").classList.toggle("hidden", !n);
    $("#voiceMute").checked = window.HOIVoice.muted;
  }
  $("#voiceMute").addEventListener("change", () => { if (window.HOIVoice) window.HOIVoice.setMuted($("#voiceMute").checked); });
  function consentUi() {
    $("#vConsentRow").classList.toggle("hidden", V.consent);
    $("#vConsent").checked = V.consent;
  }
  function openVoice(autoMic) {
    $("#voice").classList.remove("hidden"); consentUi();
    if (!$("#vLog").children.length) vLog(t("voice_hint"), "bot");
    if (autoMic && V.consent) startVoiceRec(); else if (!V.consent) vState(t("voice_tick"));
  }
  function closeVoice() {
    stopVoiceRec(true);
    $("#voice").classList.add("hidden"); $("#vConfirm").innerHTML = ""; V.action = null; vState("");
    if (window.HOIVoice) window.HOIVoice.stop();
  }
  async function voiceCommand(text) {
    text = (text || "").trim().slice(0, 300);
    if (!text) return;
    vLog(text, "me"); $("#vConfirm").innerHTML = ""; V.action = null; vState(t("working"));
    try {
      const r = await api("POST", "/me/voice/command", { text, lang: S.lang });
      vState(""); vLog(r.reply, "bot"); vSpeak(r.reply, r.lang);
      const a = r.proposed_action;
      if (a) {
        V.action = a;
        $("#vConfirm").innerHTML = `<div class="vconfirm anim"><b>${esc(a.label)}</b><div class="row"><button type="button" class="btn" data-vno>${esc(t("not_now"))}</button>` +
          `<button type="button" class="btn primary" data-vyes>${esc(t("confirm"))}</button></div></div>`;
      }
    } catch (err) { vState(err.message); }
  }
  async function voiceConfirm(yes) {
    const a = V.action; V.action = null; $("#vConfirm").innerHTML = "";
    if (!a) return;
    if (!yes) { vLog(t("cancelled"), "bot"); return; }
    if (a.action === "photo") { vLog(t("voice_photo"), "bot"); closeVoice(); show("jobs"); openCamera(a.params.job_id, a.params.kind); return; }
    try {
      await api("POST", "/me/voice/act", { action: a.action, params: a.params });
      vLog(t("voice_done"), "bot"); vSpeak(t("voice_done"), S.lang); toast(t("voice_done")); await pollJobs();
    } catch (err) { vLog(err.message.includes("no longer") ? t("gone") : err.message, "bot"); await pollJobs(); }
  }
  function pickMime() {
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return "";
    return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
  }
  async function startVoiceRec() {
    if (V.rec) { stopVoiceRec(false); return; }
    if (!V.consent) { vState(t("voice_tick")); consentUi(); return; }
    if (!navigator.mediaDevices || !window.MediaRecorder) { vState(t("no_mic")); return; }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (e) { vState(t("mic_denied")); return; }
    const mime = pickMime();
    let rec;
    try { rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream); } catch (e) { stream.getTracks().forEach((x) => x.stop()); vState(t("no_mic")); return; }
    const chunks = [], t0 = Date.now();
    const state = { rec, cancel: false, timer: setTimeout(() => stopVoiceRec(false), 30000) };
    V.rec = state;
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = async () => {
      stream.getTracks().forEach((x) => x.stop());
      $("#vMic").classList.remove("rec");
      if (state.cancel) { vState(""); return; }
      $("#vMic").classList.add("busy"); vState(t("working"));
      try {
        const blob = new Blob(chunks, { type: rec.mimeType || mime || "audio/webm" });
        const fd = new FormData();
        fd.append("audio", blob, "voice." + (blob.type.includes("mp4") ? "mp4" : blob.type.includes("ogg") ? "ogg" : "webm"));
        fd.append("consent", "true"); fd.append("lang", S.lang); fd.append("seconds", String(Math.round((Date.now() - t0) / 1000)));
        const r = await api("POST", "/me/voice/transcribe", fd, true);
        const text = (r.text || "").trim();
        if (!text) { vState(t("no_catch")); return; }
        vState(""); await voiceCommand(text);
      } catch (err) { vState(err.message || t("no_catch")); }
      finally { $("#vMic").classList.remove("busy"); }
    };
    rec.start(); $("#vMic").classList.add("rec"); vState(t("listening"));
    if (window.HOIVoice) window.HOIVoice.stop();
  }
  function stopVoiceRec(cancel) {
    if (!V.rec) return;
    const state = V.rec; V.rec = null;
    clearTimeout(state.timer); state.cancel = !!cancel;
    try { state.rec.stop(); } catch (e) { /* stopped */ }
  }
  $("#voiceFab").addEventListener("click", () => openVoice(true));
  $("#vClose").addEventListener("click", closeVoice);
  $("#vMic").addEventListener("click", startVoiceRec);
  $("#vConsent").addEventListener("change", () => { V.consent = $("#vConsent").checked; local.set("hoi.voice_consent", V.consent ? "1" : "0"); vState(V.consent ? "" : t("voice_tick")); });
  $("#vForm").addEventListener("submit", (e) => { e.preventDefault(); const v = $("#vText").value; $("#vText").value = ""; voiceCommand(v); });
  $("#voice").addEventListener("click", (e) => {
    const c = e.target.closest("[data-vchip]"); if (c) { voiceCommand(c.dataset.vchip); return; }
    if (e.target.closest("[data-vyes]")) { voiceConfirm(true); return; }
    if (e.target.closest("[data-vno]")) voiceConfirm(false);
  });

  // ---------------------------------------------------------------- PWA
  let deferredPrompt = null;
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredPrompt = e; $("#install").classList.remove("hidden"); });
  $("#install").addEventListener("click", async () => { if (deferredPrompt) { deferredPrompt.prompt(); deferredPrompt = null; $("#install").classList.add("hidden"); } });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  const net = () => $("#offline").classList.toggle("hidden", navigator.onLine);
  window.addEventListener("online", net); window.addEventListener("offline", net); net();

  // ---------------------------------------------------------------- start
  (async () => {
    applyLang();
    try { const demos = await (await fetch("/auth/demo-accounts")).json(); if (demos.some((d) => d.username === "E134")) $("#demoBtn").classList.remove("hidden"); } catch (e) { /* offline */ }
    S.refresh = localStorage.getItem("hoi.rt") || sessionStorage.getItem("hoi.rt");
    S.remember = !!localStorage.getItem("hoi.rt") || !sessionStorage.getItem("hoi.rt");
    if (S.refresh && await refresh() && S.user?.role === "worker") { await boot(); return; }
    saveRefresh(null);
    $("#login").classList.remove("hidden");
  })();
})();
