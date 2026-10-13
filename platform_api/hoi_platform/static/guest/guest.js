// Guest concierge (room QR page). The QR carries a random room token (?t=...). No login, no personal data.
// Plain JS, strict CSP (no inline scripts/styles/handlers). Voice: MediaRecorder -> /transcribe -> /chat; replies are
// spoken with the browser's speechSynthesis. Nothing is executed until the guest taps Confirm (-> /actions).
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode: keep in memory only */ } },
  };
  const MAX_REC_S = 60;

  const T = {
    en: {
      offline: "You are offline. We'll reconnect automatically.", room: "Room", demo: "Demo hotel · synthetic data",
      ask: "Ask", explore: "Explore", requests: "My requests", checkout: "Checkout", ask_title: "Ask me anything",
      sound_on: "Sound on", sound_off: "Muted", voice: "Voice",
      ai_notice: "Messages and voice are processed by a third-party AI service; please don't share personal details (names, phone, payment).",
      consent: "I agree that my voice is sent to a third-party AI service to turn it into text. It is not stored.",
      type_instead: "Type instead", allow_mic: "Allow and speak", type_here: "Type your message",
      sub: "Tap a request. The right team member is notified at once.", quick_requests: "Quick requests", note: "Anything to add? (optional)",
      status: "Your requests", none: "No requests yet.", sent: "Request sent. The team has been notified.",
      privacy: "We don't ask for your name or phone number. For emergencies, call the front desk.",
      received: "received", "on the way": "on the way", done: "done", bad: "This QR code is not valid. Please call the front desk.",
      net: "Network problem. Please try again.", listening: "Listening… tap again to stop", working: "Understanding…",
      heard: "Heard", no_catch: "Didn't catch that — try again or type.", mic_denied: "Microphone blocked. Allow it in your browser settings, or type.",
      no_mic: "Voice isn't supported on this browser. Please type.", hello: "Namaste! I'm your digital concierge. Ask me about Wi-Fi, meals, checkout or anything you need.",
      confirm: "Confirm", not_now: "Not now", done_ok: "Done! ", cancelled: "Okay, nothing was sent.",
      problems: "Report a problem", requests_h: "Ask for something", alert_now: "Alert front desk now", call: "Call",
      alert_sent: "The front desk has been alerted. Stay calm; help is coming.",
      chips: ["Wi-Fi?", "Breakfast time?", "Towels please", "Late checkout", "Checkout time?", "Nearby places"],
      express: "Express checkout", leave_time: "What time will you leave?", luggage: "I'd like help with my luggage", book_checkout: "Book express checkout",
      co_hint: "Checkout is at {t}. The front desk gets everything ready; your room is released at the time you choose.",
      co_booked: "Express checkout booked for {t}{l}.", co_lug: " with luggage help", co_done: "Checked out. Thank you for staying with us!",
      late: "Late checkout", until: "Until", reason: "Reason (optional)", ask_late: "Ask for late checkout",
      late_hint: "Possible until {t}, subject to availability. The manager approves it.", late_none: "Late checkout is not offered here.",
      late_pending: "Requested until {t}. Waiting for the manager's approval.", late_ok: "Approved until {t}.", late_no: "Sorry, late checkout until {t} was declined.",
      feedback: "How was your stay?", comment: "Comment", comment_ph: "Tell us more (optional)", send_feedback: "Send feedback",
      fb_thanks: "Thank you for your feedback!", bill: "Your bill", bill_est: "Estimate from listed prices", total: "Estimated total",
      wifi: "Wi-Fi", network: "Network", password: "Password", times: "Check-in & checkout", checkin: "Check-in", checkout_t: "Checkout",
      amenities: "Amenities", dining: "Dining menu", policies: "House rules", nearby: "Nearby", faq: "Questions", contacts: "Call us (dial from the room phone)",
      ext: "ext.", stage_open: "Received", stage_accepted: "Accepted", stage_in_progress: "In progress", stage_done: "Done",
      tooLong: "Recording stopped at 60 seconds.",
      team: { housekeeping: "Housekeeping", fnb_service: "Room service", kitchen: "Kitchen", maintenance: "Maintenance", front_office: "Front desk", security: "Security", generic: "Hotel team" },
    },
    hi: {
      offline: "आप ऑफ़लाइन हैं। इंटरनेट आते ही फिर जुड़ जाएगा।", room: "कमरा", demo: "डेमो होटल · सिंथेटिक डेटा",
      ask: "पूछें", explore: "होटल", requests: "मेरी माँगें", checkout: "चेकआउट", ask_title: "कुछ भी पूछिए",
      sound_on: "आवाज़ चालू", sound_off: "आवाज़ बंद", voice: "आवाज़",
      ai_notice: "संदेश और आवाज़ एक थर्ड-पार्टी AI सेवा प्रोसेस करती है; कृपया निजी जानकारी (नाम, फ़ोन, भुगतान) न लिखें।",
      consent: "मैं सहमत हूँ कि मेरी आवाज़ को टेक्स्ट बनाने के लिए थर्ड-पार्टी AI सेवा को भेजा जाए। इसे सेव नहीं किया जाता।",
      type_instead: "टाइप करूँगा", allow_mic: "अनुमति दें और बोलें", type_here: "अपना संदेश लिखें",
      sub: "एक विकल्प चुनें। सही स्टाफ़ को तुरंत सूचना मिलेगी।", quick_requests: "जल्दी माँगें", note: "कुछ और बताना है? (वैकल्पिक)",
      status: "आपकी माँगें", none: "अभी कोई माँग नहीं।", sent: "माँग भेज दी गई। टीम को सूचना मिल गई है।",
      privacy: "हम आपका नाम या फ़ोन नंबर नहीं माँगते। आपात स्थिति में फ़्रंट डेस्क को कॉल करें।",
      received: "मिल गई", "on the way": "रास्ते में", done: "पूरा", bad: "यह QR कोड मान्य नहीं है। फ़्रंट डेस्क को कॉल करें।",
      net: "नेटवर्क की समस्या। फिर कोशिश करें।", listening: "सुन रही हूँ… रोकने के लिए फिर दबाएँ", working: "समझ रही हूँ…",
      heard: "सुना", no_catch: "समझ नहीं आया — फिर बोलें या टाइप करें।", mic_denied: "माइक बंद है। ब्राउज़र सेटिंग में अनुमति दें, या टाइप करें।",
      no_mic: "इस ब्राउज़र में आवाज़ नहीं चलती। कृपया टाइप करें।", hello: "नमस्ते! मैं आपका डिजिटल कंसीयर्ज हूँ। वाई-फ़ाई, खाना, चेकआउट या कुछ भी पूछिए।",
      confirm: "पक्का करें", not_now: "अभी नहीं", done_ok: "हो गया! ", cancelled: "ठीक है, कुछ नहीं भेजा।",
      problems: "कोई परेशानी बताएँ", requests_h: "कुछ मँगवाएँ", alert_now: "फ़्रंट डेस्क को अभी अलर्ट करें", call: "कॉल करें",
      alert_sent: "फ़्रंट डेस्क को अलर्ट भेज दिया गया है। घबराइए नहीं, मदद आ रही है।",
      chips: ["वाई-फ़ाई?", "नाश्ता कब है?", "तौलिये चाहिए", "लेट चेकआउट", "चेकआउट कब है?", "आसपास घूमने की जगह"],
      express: "एक्सप्रेस चेकआउट", leave_time: "आप कितने बजे निकलेंगे?", luggage: "सामान में मदद चाहिए", book_checkout: "एक्सप्रेस चेकआउट बुक करें",
      co_hint: "चेकआउट {t} बजे है। फ़्रंट डेस्क सब तैयार रखेगा; आपके चुने समय पर कमरा खाली माना जाएगा।",
      co_booked: "एक्सप्रेस चेकआउट {t} बजे बुक है{l}।", co_lug: ", सामान में मदद के साथ", co_done: "चेकआउट हो गया। हमारे साथ रहने के लिए धन्यवाद!",
      late: "लेट चेकआउट", until: "कब तक", reason: "कारण (वैकल्पिक)", ask_late: "लेट चेकआउट माँगें",
      late_hint: "{t} बजे तक संभव, उपलब्धता के अनुसार। मैनेजर मंज़ूरी देंगे।", late_none: "यहाँ लेट चेकआउट नहीं है।",
      late_pending: "{t} बजे तक का अनुरोध भेजा गया। मैनेजर की मंज़ूरी का इंतज़ार।", late_ok: "{t} बजे तक मंज़ूर।", late_no: "माफ़ कीजिए, {t} बजे तक लेट चेकआउट मंज़ूर नहीं हुआ।",
      feedback: "आपका स्टे कैसा रहा?", comment: "टिप्पणी", comment_ph: "और बताइए (वैकल्पिक)", send_feedback: "फ़ीडबैक भेजें",
      fb_thanks: "आपके फ़ीडबैक के लिए धन्यवाद!", bill: "आपका बिल", bill_est: "सूची के दामों से अनुमान", total: "अनुमानित कुल",
      wifi: "वाई-फ़ाई", network: "नेटवर्क", password: "पासवर्ड", times: "चेक-इन और चेकआउट", checkin: "चेक-इन", checkout_t: "चेकआउट",
      amenities: "सुविधाएँ", dining: "खाने का मेन्यू", policies: "होटल के नियम", nearby: "आसपास", faq: "सवाल-जवाब", contacts: "कॉल करें (कमरे के फ़ोन से)",
      ext: "एक्सटें.", stage_open: "मिल गई", stage_accepted: "स्वीकार", stage_in_progress: "काम जारी", stage_done: "पूरा",
      tooLong: "60 सेकंड पर रिकॉर्डिंग रुक गई।",
      team: { housekeeping: "हाउसकीपिंग", fnb_service: "रूम सर्विस", kitchen: "किचन", maintenance: "मेंटेनेंस", front_office: "फ़्रंट डेस्क", security: "सिक्योरिटी", generic: "होटल टीम" },
    },
  };
  const S = {
    lang: store.get("hoi.guest.lang") === "hi" ? "hi" : "en", data: null, history: [], muted: !!(window.HOIVoice && window.HOIVoice.muted),
    consent: store.get("hoi.guest.voice_consent") === "1", tab: "ask", rating: 0, rec: null, pendingMic: null, lastReqSig: "",
  };
  // Request -> department, for the role avatar (never a staff id). Uses r.department when the API sends it; otherwise the
  // quick-request menu key behind the title (mirrors GUEST_MENU in services/rooms.py).
  const KEY_DEPT = { towels: "housekeeping", cleaning: "housekeeping", water: "housekeeping", amenities: "housekeeping", tea: "fnb_service",
    food: "fnb_service", ac: "maintenance", hot_water: "maintenance", electrical: "maintenance", other: "front_office" };
  function reqDept(r) {
    if (r.department) return r.department;
    const title = String(r.title || "");
    const m = (S.data.menu || []).find((x) => title === x.label || title.startsWith(x.label + ":"));
    return (m && KEY_DEPT[m.key]) || "generic";
  }
  $("#hotelLogo").addEventListener("error", () => { $("#logoPlate").classList.add("hidden"); $("#hotel").classList.remove("hidden"); });
  const token = new URLSearchParams(location.search).get("t") || "";
  const base = `/public/guest/${encodeURIComponent(token)}`;
  const tr = (k) => (T[S.lang] || T.en)[k] ?? T.en[k] ?? k;
  const fmt = (k, o) => tr(k).replace(/\{(\w)\}/g, (_, x) => o[x] ?? "");

  // ---------------------------------------------------------------- api
  async function api(method, path, body, isForm) {
    const opts = { method, headers: {} };
    if (body !== undefined) { if (isForm) opts.body = body; else { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); } }
    let r;
    try { r = await fetch(base + path, opts); } catch (e) { const err = new Error(tr("net")); err.status = 0; throw err; }
    let j = null;
    try { j = await r.json(); } catch (e) { /* empty */ }
    if (!r.ok) {
      let msg = j && typeof j.detail === "string" ? j.detail : tr("net");
      if (r.status === 429) msg = S.lang === "hi" ? "बहुत सारे अनुरोध। एक मिनट रुककर फिर कोशिश करें।" : "Too many tries. Please wait a minute and try again.";
      const err = new Error(msg); err.status = r.status; throw err;
    }
    return j;
  }
  function fail(msg) { $("#err").textContent = msg; $("#err").classList.remove("hidden"); setTimeout(() => $("#err").classList.add("hidden"), 6000); }
  function toast(msg) { const el = document.createElement("div"); el.className = "toast"; el.textContent = msg; document.body.appendChild(el); setTimeout(() => el.remove(), 2800); }

  // ---------------------------------------------------------------- paint
  function paint() {
    document.documentElement.lang = S.lang;
    $$("[data-t]").forEach((el) => { el.textContent = tr(el.dataset.t); });
    $$("[data-tph]").forEach((el) => { el.placeholder = tr(el.dataset.tph); });
    $$("[data-lang]").forEach((b) => b.classList.toggle("on", b.dataset.lang === S.lang));
    $("#muteTxt").textContent = tr(S.muted ? "sound_off" : "sound_on");
    $("#muteIco").textContent = S.muted ? "🔇" : "🔊";
    $("#mute").setAttribute("aria-pressed", S.muted ? "true" : "false");
    $("#chips").innerHTML = tr("chips").map((c) => `<button type="button" class="chip-btn" data-chip="${esc(c)}">${esc(c)}</button>`).join("");
    if (!S.data) return;
    const d = S.data, p = d.profile || {};
    $("#hotel").textContent = p.display_name || d.hotel;
    paintLogo(window.HOI_SAFE_IMG(p.logo_url), p.display_name || d.hotel);
    paintCover(window.HOI_SAFE_IMG(p.cover_photo_url), p.cover_photo_credit || "");
    $("#roomNo").textContent = d.room;
    $("#welcome").textContent = p.welcome || "";
    $("#demoTag").classList.toggle("hidden", !d.synthetic && !p.synthetic);
    if (!$("#thread").children.length) bot(tr("hello"), null, null, true);
    paintMenu(); paintRequests(); paintExplore(); paintCheckout();
  }

  // Hotel logo on a white plate (keeps the brand colours readable on the orange header); hotel name text otherwise.
  function paintLogo(url, name) {
    const img = $("#hotelLogo"), plate = $("#logoPlate");
    if (!url) { plate.classList.add("hidden"); $("#hotel").classList.remove("hidden"); return; }
    img.alt = name || "";
    if (img.getAttribute("src") !== url) img.src = url;
    plate.classList.remove("hidden"); $("#hotel").classList.add("hidden");
  }

  // Property photo behind the header (licensed photo of the area; credit line shown under the header).
  function paintCover(url, credit) {
    const hero = $("#hero");
    if (!url) { hero.classList.remove("photo"); hero.style.backgroundImage = ""; $("#photoCredit").classList.add("hidden"); return; }
    hero.classList.add("photo");
    hero.style.backgroundImage = `linear-gradient(180deg,rgba(10,20,40,.35),rgba(10,20,40,.78)),url("${url}")`;
    $("#photoCredit").textContent = credit; $("#photoCredit").classList.toggle("hidden", !credit);
  }

  function paintMenu() {
    const opt = (m) => `<button type="button" class="opt${m.urgent ? " urgent" : ""}" data-key="${esc(m.key)}">${esc(S.lang === "hi" ? m.label_hi : m.label)}<small>${esc(S.lang === "hi" ? m.label : m.label_hi)}</small></button>`;
    const reqs = S.data.menu.filter((m) => m.group !== "problem"), probs = S.data.menu.filter((m) => m.group === "problem");
    $("#menu").innerHTML = `<h3 class="mgroup">${esc(tr("requests_h"))}</h3><div class="grid">${reqs.map(opt).join("")}</div>` +
      (probs.length ? `<h3 class="mgroup">${esc(tr("problems"))}</h3><div class="grid">${probs.map(opt).join("")}</div>` : "");
  }

  function paintRequests() {
    const reqs = S.data.requests || [];
    const order = ["open", "accepted", "in_progress", "done"];
    const tone = { open: "watch", accepted: "watch", in_progress: "watch", done: "low" };
    $("#list").innerHTML = reqs.length ? reqs.map((r) => {
      const i = order.indexOf(r.stage);
      const dep = reqDept(r), team = (T[S.lang].team || T.en.team)[dep] || T.en.team.generic;
      return `<div class="st"><div class="row"><img class="ravatar" src="${esc(window.HOI_AVATAR(dep))}" alt="" width="40" height="40">` +
        `<span><b>${esc(r.title)}</b><br><span class="muted">${esc(team)} · ${esc((r.at || "").slice(11, 16))}</span></span>` +
        `<span class="chip ${tone[r.stage] || "gray"}">${esc(tr("stage_" + r.stage))}</span></div>` +
        `<div class="prog" aria-hidden="true">${order.map((_, k) => `<span class="${k <= i ? "on" : ""}"></span>`).join("")}</div></div>`;
    }).join("") : `<p class="muted">${esc(tr("none"))}</p>`;
  }

  function section(title, inner) { return inner ? `<div class="card"><h3>${esc(title)}</h3>${inner}</div>` : ""; }

  function paintExplore() {
    const p = S.data.profile || {};
    const lc = p.late_checkout || {};
    let h = "";
    if (p.wifi && p.wifi.network) h += section(tr("wifi"), `<div class="kv"><span>${esc(tr("network"))}</span><span class="wifi">${esc(p.wifi.network)}</span></div>` +
      (p.wifi.password_hint ? `<div class="kv"><span>${esc(tr("password"))}</span><span>${esc(p.wifi.password_hint)}</span></div>` : ""));
    h += section(tr("times"), `<div class="kv"><span>${esc(tr("checkin"))}</span><span>${esc(p.checkin_time)}</span></div><div class="kv"><span>${esc(tr("checkout_t"))}</span><span>${esc(p.checkout_time)}</span></div>` +
      (lc.allowed ? `<div class="kv"><span>${esc(tr("late"))}</span><span>${esc(fmt("late_hint", { t: lc.latest }))}</span></div>` : ""));
    h += section(tr("amenities"), (p.amenities || []).map((a) => `<div class="kv"><span><b>${esc(a.name)}</b>${a.where ? `<br><span class="muted">${esc(a.where)}</span>` : ""}${a.note ? `<br><span class="muted">${esc(a.note)}</span>` : ""}</span><span>${esc(a.hours)}</span></div>`).join(""));
    h += section(tr("dining"), (p.dining || []).map((x) => `<div class="dish"><span>${x.veg === true ? '<i class="veg" aria-label="veg"></i>' : x.veg === false ? '<i class="veg nonveg" aria-label="non-veg"></i>' : ""}${esc(x.item)}${x.hours ? `<br><span class="muted">${esc(x.hours)}</span>` : ""}</span><span>${x.price_inr != null ? "₹" + esc(x.price_inr) : ""}</span></div>`).join(""));
    h += section(tr("policies"), (p.policies || []).map((x) => `<details><summary>${esc(x.title)}</summary><p>${esc(x.text)}</p></details>`).join(""));
    h += section(tr("nearby"), (p.nearby || []).map((x) => `<div class="kv"><span><b>${esc(x.name)}</b>${x.tip ? `<br><span class="muted">${esc(x.tip)}</span>` : ""}</span><span>${esc(x.distance_note)}</span></div>`).join(""));
    h += section(tr("faq"), (p.faq || []).map((x) => `<details><summary>${esc(x.q)}</summary><p>${esc(x.a)}</p></details>`).join(""));
    h += section(tr("contacts"), (p.contacts || []).map((c) => `<div class="kv"><span>${esc(c.label)}</span><span><b>${esc(tr("ext"))} ${esc(c.extension)}</b></span></div>`).join(""));
    $("#explore").innerHTML = h;
  }

  function addMinutes(hhmm, m) { const [h, mi] = hhmm.split(":").map(Number); const t = h * 60 + mi + m; return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`; }

  function paintCheckout() {
    const p = S.data.profile || {}, st = S.data.stay || {}, lc = p.late_checkout || {};
    const co = st.checkout;
    $("#coHint").textContent = fmt("co_hint", { t: p.checkout_time });
    if (co) {
      const done = co.status === "done";
      $("#coStatus").innerHTML = `<div class="statusbox ${done ? "ok" : "pending"}">${esc(done ? tr("co_done") : fmt("co_booked", { t: co.time, l: co.luggage_help ? tr("co_lug") : "" }))}</div>`;
      $("#coForm").classList.add("hidden");
    } else {
      $("#coStatus").innerHTML = ""; $("#coForm").classList.remove("hidden");
      if (!$("#coTime").value) $("#coTime").value = p.checkout_time || "11:00";
    }
    const late = st.late_checkout || { status: "none" };
    if (!lc.allowed) { $("#lateStatus").innerHTML = `<p class="muted">${esc(tr("late_none"))}</p>`; $("#lateForm").classList.add("hidden"); }
    else {
      const box = { pending: ["pending", "late_pending"], approved: ["ok", "late_ok"], declined: ["no", "late_no"] }[late.status];
      $("#lateStatus").innerHTML = box ? `<div class="statusbox ${box[0]}">${esc(fmt(box[1], { t: late.until }))}${late.note ? `<br><span class="muted">${esc(late.note)}</span>` : ""}</div>` : "";
      $("#lateForm").classList.toggle("hidden", late.status === "pending" || late.status === "approved");
      $("#lateHint").textContent = fmt("late_hint", { t: lc.latest });
      const opts = [];
      for (let t = addMinutes(p.checkout_time, 30); t <= lc.latest; t = addMinutes(t, 30)) opts.push(t);
      const cur = $("#lateUntil").value;
      $("#lateUntil").innerHTML = opts.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
      if (cur && opts.includes(cur)) $("#lateUntil").value = cur;
    }
    if (st.feedback_given) { $("#fbForm").classList.add("hidden"); $("#fbDone").classList.remove("hidden"); $("#fbDone").innerHTML = `<div class="statusbox ok">${esc(tr("fb_thanks"))} ${"★".repeat(st.feedback_rating || 0)}</div>`; }
    else {
      $("#fbForm").classList.remove("hidden"); $("#fbDone").classList.add("hidden");
      $("#stars").innerHTML = [1, 2, 3, 4, 5].map((n) => `<button type="button" role="radio" aria-checked="${n === S.rating}" aria-label="${n}" class="star ${n <= S.rating ? "on" : ""}" data-star="${n}">★</button>`).join("");
      $("#fbBtn").disabled = !S.rating;
    }
  }

  async function loadBill() {
    try {
      const b = await api("GET", "/bill");
      const rows = (b.requests_with_charges || []).map((x) => `<div class="est"><span>${esc(x.item)}</span><span>₹${esc(x.price_inr)}</span></div>`).join("");
      $("#bill").innerHTML = `<p class="muted">${esc(b.note)}.</p>` + (rows ? `<div class="eyebrow">${esc(tr("bill_est"))}</div>${rows}<div class="est"><b>${esc(tr("total"))}</b><b>₹${esc(b.estimate_total_inr)}</b></div><p class="muted">${esc(b.estimate_note)}</p>` : "");
    } catch (e) { $("#bill").innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
  }

  // ---------------------------------------------------------------- data
  async function load() {
    try {
      S.data = await api("GET", "");
      if (S.data.brand_color) document.documentElement.style.setProperty("--brand", S.data.brand_color);
      paint();
    } catch (e) { fail(e.status === 404 ? tr("bad") : e.message); }
  }
  async function refreshRequests() {
    if (!S.data || document.hidden) return;
    try {
      const r = await api("GET", "/requests");
      const sig = JSON.stringify(r.requests.map((q) => q.id + q.stage));
      if (S.lastReqSig && sig !== S.lastReqSig && S.tab !== "requests") $("#reqDot").classList.remove("hidden");
      S.lastReqSig = sig; S.data.requests = r.requests; paintRequests();
    } catch (e) { /* offline: keep the last list */ }
  }

  // ---------------------------------------------------------------- tabs
  function show(tab) {
    S.tab = tab;
    $$(".tab").forEach((el) => el.classList.toggle("hidden", el.id !== "tab-" + tab));
    $$(".tabbar button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
    if (tab === "requests") { $("#reqDot").classList.add("hidden"); refreshRequests(); }
    if (tab === "checkout") { load(); loadBill(); }
    window.scrollTo({ top: 0 });
  }

  // ---------------------------------------------------------------- chat
  // The thread ends the Ask tab and the tab has bottom padding for the fixed dock, so the page bottom shows the newest message.
  function scrollThread() { requestAnimationFrame(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" })); }
  function me(text, cls) { const el = document.createElement("div"); el.className = "msg " + (cls || "me"); el.textContent = text; $("#thread").appendChild(el); scrollThread(); return el; }
  function bot(text, action, lang, silent) {
    const el = document.createElement("div"); el.className = "msg bot"; el.textContent = text; $("#thread").appendChild(el);
    if (action && action.urgent) {  // safety / medical: one big button + emergency numbers (tap to call)
      const c = document.createElement("div"); c.className = "confirm urgent";
      const nums = (action.emergency || []).filter((n) => /^\d{3,4}$/.test(n.tel)).map((n) => `<a class="tel" href="tel:${esc(n.tel)}">${esc(tr("call"))} ${esc(n.label)}</a>`).join("");
      c.innerHTML = `<button type="button" class="btn alert" data-yes>${esc(tr("alert_now"))}</button><div class="tels">${nums}</div>`;
      c._action = action; $("#thread").appendChild(c);
    } else if (action) {
      const c = document.createElement("div"); c.className = "confirm";
      c.innerHTML = `<b>${esc(S.lang === "hi" && action.label_hi ? action.label_hi : action.label)}</b><div class="row"><button type="button" class="btn" data-no>${esc(tr("not_now"))}</button><button type="button" class="btn primary" data-yes>${esc(tr("confirm"))}</button></div>`;
      c._action = action; $("#thread").appendChild(c);
    }
    scrollThread();
    if (!silent) speak(text, lang);
  }
  function typing(on) {
    let el = $("#typing");
    if (on && !el) { el = document.createElement("div"); el.id = "typing"; el.className = "msg bot typing"; el.innerHTML = "<i></i><i></i><i></i>"; $("#thread").appendChild(el); scrollThread(); }
    if (!on && el) el.remove();
  }
  async function send(text) {
    text = (text || "").trim().slice(0, 500);
    if (!text) return;
    me(text);
    typing(true);
    try {
      const r = await api("POST", "/chat", { message: text, lang: S.lang, history: S.history.slice(-6) });
      typing(false);
      S.history.push({ role: "user", text }, { role: "assistant", text: r.reply });
      S.history = S.history.slice(-6);
      bot(r.reply, r.proposed_action, r.lang);
    } catch (e) { typing(false); bot(e.message, null, null, true); }
  }
  async function confirmAction(card, yes) {
    const action = card._action;
    card.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    if (!yes) { card.remove(); bot(tr("cancelled"), null, S.lang); return; }
    try {
      const params = { ...action.params };
      if (action.action === "feedback") params.lang = S.lang;
      await api("POST", "/actions", { action: action.action, params });
      card.classList.add("done");
      const row = card.querySelector(".row") || card.querySelector(".alert");
      if (row) row.remove();
      const msg = action.urgent ? tr("alert_sent") : { request: tr("sent"), checkout: fmt("co_booked", { t: params.time, l: params.luggage_help ? tr("co_lug") : "" }), late_checkout: fmt("late_pending", { t: params.until }), feedback: tr("fb_thanks") }[action.action];
      bot(tr("done_ok") + msg, null, S.lang);
      await load();
    } catch (e) { card.querySelectorAll("button").forEach((b) => { b.disabled = false; }); bot(e.message, null, null, true); }
  }

  // ---------------------------------------------------------------- speech out (/shared/voice.js: server voice if configured, else the browser)
  async function serverVoice(text, lang) {
    if (!S.data || !S.data.voice || !S.data.voice.server_tts) return null;
    const r = await fetch(base + "/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, lang }) });
    return r.status === 200 ? r.blob() : null;
  }
  function speak(text, lang) {
    if (!window.HOIVoice) return;
    window.HOIVoice.speak(text, lang || S.lang, { server: serverVoice }).catch(() => {});
  }
  async function fillVoices() {
    if (!window.HOIVoice) return;
    const n = await window.HOIVoice.fillPicker($("#voicePick"), S.lang);
    $("#voiceRow").classList.toggle("hidden", !n);
  }

  // ---------------------------------------------------------------- voice in (MediaRecorder -> /transcribe)
  function micState(text) { $("#micState").textContent = text || ""; }
  function pickMime() {
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return "";
    return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
  }
  function needConsent(then) {
    if (S.consent) return false;
    S.pendingMic = then; $("#consent").classList.remove("hidden"); $("#consentBox").focus();
    return true;
  }
  async function startRec(target) {
    if (S.rec) { stopRec(); return; }
    if (!navigator.mediaDevices || !window.MediaRecorder) { micState(tr("no_mic")); return; }
    if (needConsent(() => startRec(target))) return;
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (e) { micState(tr("mic_denied")); return; }
    const mime = pickMime();
    let rec;
    try { rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream); } catch (e) { stream.getTracks().forEach((t) => t.stop()); micState(tr("no_mic")); return; }
    const chunks = [];
    const t0 = Date.now();
    S.rec = { rec, stream, target, timer: setTimeout(() => { micState(tr("tooLong")); stopRec(); }, MAX_REC_S * 1000) };
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const btn = target === "fb" ? $("#fbMic") : $("#mic");
      btn.classList.remove("rec"); btn.classList.add("busy");
      micState(tr("working"));
      const blob = new Blob(chunks, { type: rec.mimeType || mime || "audio/webm" });
      const secs = (Date.now() - t0) / 1000;
      try {
        const fd = new FormData();
        const ext = (blob.type.includes("mp4") ? "mp4" : blob.type.includes("ogg") ? "ogg" : "webm");
        fd.append("audio", blob, "voice." + ext); fd.append("consent", "true"); fd.append("lang", S.lang); fd.append("seconds", String(Math.round(secs)));
        const r = await api("POST", "/transcribe", fd, true);
        const text = (r.text || "").trim();
        if (!text) { micState(tr("no_catch")); return; }
        micState("");
        if (target === "fb") { $("#fbText").value = ($("#fbText").value + " " + text).trim().slice(0, 1000); return; }
        $("#msg").value = text;
        const h = me(`${tr("heard")}: “${text}”`, "heard");
        setTimeout(() => { h.remove(); $("#msg").value = ""; send(text); }, 1000);
      } catch (e) { micState(e.status === 503 || e.status === 422 ? e.message : tr("no_catch")); }
      finally { btn.classList.remove("busy"); }
    };
    rec.start();
    (target === "fb" ? $("#fbMic") : $("#mic")).classList.add("rec");
    micState(tr("listening"));
    if (window.HOIVoice) window.HOIVoice.stop();
  }
  function stopRec() {
    if (!S.rec) return;
    clearTimeout(S.rec.timer);
    const { rec } = S.rec; S.rec = null;
    try { rec.stop(); } catch (e) { /* already stopped */ }
  }

  // ---------------------------------------------------------------- events
  document.addEventListener("click", async (e) => {
    const l = e.target.closest("[data-lang]");
    if (l) { S.lang = l.dataset.lang; store.set("hoi.guest.lang", S.lang); micState(""); paint(); fillVoices(); return; }
    const tb = e.target.closest("[data-tab]");
    if (tb) { show(tb.dataset.tab); return; }
    const chip = e.target.closest("[data-chip]");
    if (chip) { send(chip.dataset.chip); return; }
    const yes = e.target.closest("[data-yes]"), no = e.target.closest("[data-no]");
    if (yes || no) { confirmAction((yes || no).closest(".confirm"), !!yes); return; }
    const star = e.target.closest("[data-star]");
    if (star) { S.rating = Number(star.dataset.star); paintCheckout(); return; }
    const b = e.target.closest("[data-key]");
    if (!b) return;
    $$(".opt").forEach((x) => { x.disabled = true; });
    try {
      const j = await api("POST", "/requests", { key: b.dataset.key, note: $("#note").value });
      S.data = j; $("#note").value = ""; paint(); toast(tr("sent"));
    } catch (err) { fail(err.message); }
    finally { $$(".opt").forEach((x) => { x.disabled = false; }); }
  });
  $("#askForm").addEventListener("submit", (e) => { e.preventDefault(); const v = $("#msg").value; $("#msg").value = ""; send(v); });
  $("#mic").addEventListener("click", () => startRec("chat"));
  $("#fbMic").addEventListener("click", () => startRec("fb"));
  $("#mute").addEventListener("click", () => { S.muted = !S.muted; if (window.HOIVoice) window.HOIVoice.setMuted(S.muted); paint(); });
  $("#consentYes").addEventListener("click", () => {
    if (!$("#consentBox").checked) { $("#consentBox").focus(); micState(tr("consent")); return; }
    S.consent = true; store.set("hoi.guest.voice_consent", "1"); $("#consent").classList.add("hidden"); micState("");
    const go = S.pendingMic; S.pendingMic = null; if (go) go();
  });
  $("#consentNo").addEventListener("click", () => { $("#consent").classList.add("hidden"); S.pendingMic = null; $("#msg").focus(); });
  $("#coBtn").addEventListener("click", async () => {
    $("#coBtn").disabled = true;
    try { await api("POST", "/checkout", { time: $("#coTime").value, luggage_help: $("#coLug").checked }); await load(); toast(tr("done_ok")); }
    catch (e) { fail(e.message); } finally { $("#coBtn").disabled = false; }
  });
  $("#lateBtn").addEventListener("click", async () => {
    $("#lateBtn").disabled = true;
    try { await api("POST", "/late-checkout", { until: $("#lateUntil").value, reason: $("#lateReason").value }); $("#lateReason").value = ""; await load(); }
    catch (e) { fail(e.message); } finally { $("#lateBtn").disabled = false; }
  });
  $("#fbBtn").addEventListener("click", async () => {
    if (!S.rating) return;
    $("#fbBtn").disabled = true;
    try { await api("POST", "/feedback", { rating: S.rating, comment: $("#fbText").value, lang: S.lang }); $("#fbText").value = ""; await load(); }
    catch (e) { fail(e.message); $("#fbBtn").disabled = false; }
  });
  const net = () => $("#offline").classList.toggle("hidden", navigator.onLine);
  window.addEventListener("online", () => { net(); load(); }); window.addEventListener("offline", net); net();
  fillVoices();

  // ---------------------------------------------------------------- start
  paint();
  if (!token) fail(tr("bad")); else load();
  setInterval(refreshRequests, 15000);
  setInterval(() => { if (S.data && !document.hidden && S.tab === "checkout") load(); }, 30000);
})();
