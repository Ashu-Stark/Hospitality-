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
  const roleImg = (d) => `<img class="javatar" src="${esc(window.HOI_AVATAR(d))}" alt="" width="28" height="28">`;
  const shiftName = (k) => (SHIFTS[S.lang] || SHIFTS.en)[k] || k;
  const REC = {
    en: { on_time_job: "Finish a job on time", after_photo: "Add the after photo", inspection_pass: "Room passes the check first time", guest_feedback_good: "Guest gives 4-5 stars after your request" },
    hi: { on_time_job: "काम समय पर पूरा करें", after_photo: "बाद की फ़ोटो लगाएँ", inspection_pass: "कमरा पहली बार में जाँच पास करे", guest_feedback_good: "आपके काम के बाद मेहमान 4-5 स्टार दे" },
  };
  const fill = (s, o) => s.replace(/\{(\w+)\}/g, (_, k) => esc(o[k] ?? ""));
  const isHomestay = () => S.me?.mode === "homestay";
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
    if (sess.user.role !== "worker") { $("#loginErr").textContent = S.lang === "hi" ? "यह ऐप स्टाफ़ के लिए है। मैनेजर HOI डैशबोर्ड इस्तेमाल करें।" : "This app is for staff. Managers use the HOI dashboard."; $("#loginErr").classList.remove("hidden"); return; }
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
    await loadRecognition();
    renderAll();
    await pollJobs();
    clearInterval(S.poll);
    S.poll = setInterval(pollJobs, 2000);
  }

  function renderAll() {
    const emp = S.user.employee_id || S.user.username;
    $("#avatar").src = window.HOI_AVATAR(S.me?.department);
    $("#meAvatar").src = window.HOI_AVATAR(S.me?.department);
    // Hotel mark: tenant logo (e.g. /shared/brand/x-logo.svg) -> its square "-mark" sibling; hidden when none.
    const logo = window.HOI_SAFE_IMG(S.tenant?.logo_url || S.tenant?.profile?.logo_url);
    const mark = logo ? logo.replace(/-logo(\.\w+)$/, "-mark$1") : null;
    $("#brandMark").classList.toggle("hidden", !mark);
    if (mark) { $("#brandMark").src = mark; $("#brandMark").alt = S.tenant?.name || ""; }
    $("#whoName").textContent = emp;
    $("#whoDept").textContent = dept(S.me?.department);
    $("#shiftChip").textContent = S.me?.on_shift_now ? t("on_shift") : t("off_shift");
    $("#meId").textContent = emp; $("#meDeptTxt").textContent = dept(S.me?.department) || "—"; $("#meHotel").textContent = S.tenant?.name || "";
    if (S.tenant?.brand_color) document.documentElement.style.setProperty("--brand", S.tenant.brand_color);
    document.body.classList.toggle("homestay", isHomestay());
    if (S.me?.property?.name) $("#meHotel").textContent = S.me.property.name;
    renderToday(); renderJobs(); renderItems(); loadRequests(); renderRecognition();
  }

  // ---------------------------------------------------------------- recognition (own points only; positive only)
  async function loadRecognition() {
    try { S.rec = await api("GET", "/me/recognition"); } catch (e) { S.rec = null; }
  }
  function renderRecognition() {
    const el = $("#recCard"), r = S.rec;
    if (!r) { el.classList.add("hidden"); return; }
    el.classList.remove("hidden");
    const labels = REC[S.lang] || REC.en;
    const money = (v) => "₹" + Number(v || 0).toLocaleString("en-IN");
    let est;
    if (!r.budget_set) est = `<p class="muted">${esc(t("rec_no_budget"))}</p>`;
    else if (!r.eligible) est = `<p class="muted">${fill(t("rec_min"), { n: r.min_jobs, d: r.jobs_done })}</p>`;
    else est = `<div class="recest"><span>${esc(t("rec_est"))}</span><b>${esc(money(r.estimated_reward_inr))}</b></div><p class="muted small">${esc(t("rec_est_note"))}</p>`;
    const how = r.breakdown.map((b) => `<li><span>${esc(labels[b.key] || b.label)}</span><b>+${esc(b.points_each)}</b>${b.count ? `<em>${esc(b.count)}×</em>` : ""}</li>`).join("");
    const team = r.team || {};
    const board = r.leaderboard ? `<div class="eyebrow">${esc(t("rec_top"))}</div><ol class="recboard">${r.leaderboard.map((x) => `<li${x.employee_id === r.employee_id ? ' class="me"' : ""}><span>${esc(x.employee_id)}</span><b>${esc(x.points)}</b></li>`).join("")}</ol>` : "";
    el.innerHTML = `<div class="eyebrow">${esc(t("rec_title"))} · ${esc(r.month)}</div>` +
      `<div class="recpts"><b>${esc(r.points)}</b><span>${esc(t("rec_points"))}</span></div>` +
      (r.capped ? `<p class="muted">${esc(t("rec_capped"))}</p>` : "") + est +
      `<details class="rechow"><summary>${esc(t("rec_how"))}</summary><ul>${how}</ul></details>` +
      `<div class="recteam"><span class="eyebrow">${esc(t("rec_team"))}</span><div>${fill(t("rec_team_line"), { p: team.people_with_points, m: team.members, t: team.total_points })}</div></div>` +
      board + `<p class="recnever">✓ ${esc(t("rec_never"))}</p>`;
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
    if (isHomestay()) {  // homestay: no roster; the week card (same size, no layout shift) explains the small-team way of working
      const me = S.user.employee_id || S.user.username;
      const open = (S.jobs || []).filter((j) => (j.status === "offered" && j.offer_to === me) || (["accepted", "in_progress"].includes(j.status) && j.assigned_to === me)).length;
      const hero = $("#todayHero");
      hero.className = "todayhero anim";
      hero.innerHTML = `<div class="eyebrow">${esc(t("today"))} · ${esc(S.me?.property?.name || "")}</div><h2>${esc(t("hs_tasks"))}: ${esc(open)}</h2>`;
      $("#week").innerHTML = `<p class="hsnote">${esc(t("hs_tasks_sub"))}</p>`;
      $("#weekNote").textContent = "";
      $("#weekCard .eyebrow").textContent = t("your_team");
      return;
    }
    const shifts = S.me?.shifts || [];
    const curDay = S.me?.current_shift?.day;
    // The header chip follows the live "working now" list (what job offers use); if the published plan has no
    // entry for today but that list says this person is working, show the live shift so both agree.
    const cur = S.me?.current_shift;
    const today = shifts.find((s) => s.date === curDay) ||
      (S.me?.on_shift_now && cur?.shift ? { date: curDay || cur.day, shift: cur.shift, hours: cur.hours || 9 } : null);
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
    const doneNow = S.jobs.filter((j) => j.status === "done").length;
    if (S.doneSeen !== undefined && doneNow !== S.doneSeen) { await loadRecognition(); renderRecognition(); }
    S.doneSeen = doneNow;
    if (isHomestay()) renderToday();
    renderJobs();
  }

  function renderJobs() {
    const me = S.user.employee_id || S.user.username;
    const offer = S.jobs.find((j) => j.status === "offered" && j.offer_to === me);
    const active = S.jobs.filter((j) => ["accepted", "in_progress"].includes(j.status) && j.assigned_to === me);
    const done = S.jobs.filter((j) => j.status === "done" && j.assigned_to === me).slice(0, 5);
    const oEl = $("#offer");
    if (offer && oEl.dataset.oid === offer.id && oEl.dataset.mode === (isHomestay() ? "hs" : "hotel") && oEl.dataset.lang === S.lang) {
      // same offer as on screen: only the time left changes (no re-render, no flicker every poll)
      const left = offer.seconds_left || 0, total = Math.max(left, Number(oEl.dataset.total) || 30);
      const ol = oEl.querySelector(".oleft"); if (ol) ol.textContent = fill(t("answer_in"), { n: left });
      const bar = oEl.querySelector(".bar i"); if (bar) bar.style.width = Math.round((100 * left) / total) + "%";
    } else if (offer && isHomestay()) {  // homestay: a plain task card, no timer
      oEl.innerHTML = `<div class="offer simple anim"><div class="otop"><span class="sbadge s-new">${esc(t("new_task"))}</span></div>` +
        `<h2>${esc(offer.title)}</h2><div class="jmeta">${roleImg(offer.department)}<span class="jroom">${offer.room ? esc(t("room")) + " " + esc(offer.room) : ""}</span>` +
        `<span class="urg">${esc(t("urgency_" + offer.urgency))}</span></div>` +
        `<button class="btn primary big" data-act="accept" data-id="${esc(offer.id)}">${esc(t("take_it"))}</button>` +
        `<button class="btn quiet" data-act="decline" data-id="${esc(offer.id)}">${esc(t("not_now_task"))}</button></div>`;
    } else if (offer) {
      // New job: one big Accept; "Can't now" is the quiet second choice. The bar shows the time left to answer.
      const left = offer.seconds_left || 0, total = Math.max(left, 30);
      const urgent = ["high", "urgent"].includes(offer.urgency);
      oEl.dataset.total = String(total);
      oEl.innerHTML = `<div class="offer anim"><div class="otop"><span class="sbadge s-new">${esc(t("new_request"))}</span>` +
        `<span class="oleft" aria-live="off">${esc(fill(t("answer_in"), { n: left }))}</span></div>` +
        `<h2>${esc(offer.title)}</h2><div class="jmeta">${roleImg(offer.department)}<span class="jroom">${offer.room ? esc(t("room")) + " " + esc(offer.room) : esc(dept(offer.department))}</span>` +
        `<span class="urg ${urgent ? "hi" : ""}">${esc(t("urgency_" + offer.urgency))}</span></div>` +
        `<div class="bar"><i data-w="${Math.round((100 * left) / total)}"></i></div>` +
        `<button class="btn primary big" data-act="accept" data-id="${esc(offer.id)}">${esc(t("accept"))}</button>` +
        `<button class="btn quiet" data-act="decline" data-id="${esc(offer.id)}">${esc(t("decline"))}</button></div>`;
      oEl.querySelectorAll("[data-w]").forEach((i) => { i.style.width = i.dataset.w + "%"; });
    } else oEl.innerHTML = "";
    oEl.dataset.oid = offer ? offer.id : ""; oEl.dataset.mode = isHomestay() ? "hs" : "hotel"; oEl.dataset.lang = S.lang;
    // Active jobs: only the job being worked on is open, with ONE next step (Start, then Done). The photo is part of
    // that step (Start takes the before photo, Done the finish photo) and the camera opens only when it is tapped.
    // Other accepted jobs stay as short rows; "Open" makes one the current job.
    active.sort((a, b) => (a.status === "in_progress" ? 0 : 1) - (b.status === "in_progress" ? 0 : 1));
    if (!active.some((j) => j.id === S.focus)) S.focus = active.length ? active[0].id : null;
    const cur = active.find((j) => j.id === S.focus);
    const rest = active.filter((j) => j !== cur);
    const label = (j) => (j.status === "in_progress" ? "in_progress" : "accepted");
    let html = "";
    if (cur) {
      const working = cur.status === "in_progress";
      html += `<div class="job focus s-${label(cur)} anim"><div class="jtop"><span class="sbadge s-${label(cur)}">${esc(t(label(cur)))}</span>` +
        `${cur.room ? `<span class="jroomb">${esc(t("room"))} ${esc(cur.room)}</span>` : ""}</div>` +
        `<h3>${esc(cur.title)}</h3>` +
        `<ol class="steps3" aria-label="${esc(t("steps"))}"><li class="done">${esc(t("step_accept"))}</li><li class="${working ? "done" : "now"}">${esc(t("step_start"))}</li><li class="${working ? "now" : ""}">${esc(t("step_done"))}</li></ol>` +
        `<button class="btn primary big ${working ? "go-done" : "go-start"}" data-act="photo" data-kind="${working ? "after" : "before"}" data-id="${esc(cur.id)}">` +
        `${working ? "✓" : "▶"} ${esc(t(working ? "finish" : "start"))}</button>` +
        `<p class="jhint"><span aria-hidden="true">📷</span> ${esc(t(working ? "done_hint" : "start_hint"))}</p></div>`;
    }
    if (rest.length) {
      html += `<h3 class="subh">${esc(t("other_jobs"))}</h3>` + rest.map((j) =>
        `<div class="jrow s-${label(j)}"><i class="sdot" aria-hidden="true"></i><div class="jrowt"><b>${esc(j.title)}</b>` +
        `<span class="muted">${j.room ? esc(t("room")) + " " + esc(j.room) + " · " : ""}${esc(t(label(j)))}</span></div>` +
        `<button class="btn small" data-act="focus" data-id="${esc(j.id)}">${esc(t("open"))}</button></div>`).join("");
    }
    if ($("#active")._h !== html) { $("#active").innerHTML = html; $("#active")._h = html; }  // unchanged: keep the DOM (no flicker)
    $("#noJobs").classList.toggle("hidden", !!offer || active.length > 0);
    const doneHtml = done.length ? `<h3 class="subh">${esc(t("completed_recent"))}</h3>` + done.map((j) =>
      `<div class="jrow s-done"><i class="sdot" aria-hidden="true"></i><div class="jrowt"><b>${esc(j.title)}</b>` +
      `<span class="muted">${j.room ? esc(t("room")) + " " + esc(j.room) + " · " : ""}${esc((j.done_at || "").slice(11, 16))}</span></div>` +
      `<span class="sbadge s-done">${esc(t("done"))}</span></div>`).join("") : "";
    if ($("#doneList")._h !== doneHtml) { $("#doneList").innerHTML = doneHtml; $("#doneList")._h = doneHtml; }
  }

  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const id = b.dataset.id;
    if (b.dataset.act === "focus") { S.focus = id; renderJobs(); window.scrollTo({ top: 0, behavior: "auto" }); return; }
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
