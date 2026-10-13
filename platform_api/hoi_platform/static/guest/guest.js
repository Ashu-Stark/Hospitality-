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
      offline: "You are offline. We'll reconnect automatically.", room: "Room",
      ask: "Ask", explore: "Hotel info", requests: "My requests", checkout: "Check-out", ask_title: "Ask me anything",
      voice: "Choose the voice", ask_us: "Ask us", what_need: "What do you need?", voice_menu: "Spoken replies",
      speak_replies: "Read replies aloud", st_idle: "Ready to help", st_listening: "Listening…", st_thinking: "Thinking…",
      st_speaking: "Speaking…", stop: "Stop speaking", voice_on: "Voice on", voice_off: "Voice off",
      voice_on_aria: "Voice replies are on. Tap to read replies silently.", voice_off_aria: "Voice replies are off. Tap to hear replies.",
      mic_talk: "Tap to talk", mic_stop: "Listening. Tap to stop.", thinking: "Thinking",
      starters: [["towels", "🧺", "Towels", "Towels please"], ["clean", "🧹", "Room cleaning", "Please clean my room"],
        ["wifi", "📶", "Wi-Fi", "What is the Wi-Fi password?"], ["food", "🍽", "Food", "Show me the food menu"],
        ["places", "🏞", "Places nearby", "Places to visit nearby"], ["problem", "🛠", "Problem in room", ""]],
      problem_q: "Sorry about that. What is the problem? Tap one.", sent_to: "Sent to {d}",
      ai_notice: "Please don't share personal details like phone or card numbers.",
      consent: "OK to send my voice to an outside service that turns it into text. It is not saved.",
      type_instead: "Type instead", allow_mic: "Allow and speak", type_here: "Type your message",
      sub: "Tap what you need. The right person is told at once.", quick_requests: "Quick requests", note: "Anything to add? (if you like)",
      status: "Your requests", none: "No requests yet.", sent: "Request sent. The team has been notified.",
      privacy: "For emergencies, call the front desk.",
      received: "received", "on the way": "on the way", done: "done", bad: "This QR code is not valid. Please call the front desk.",
      net: "Network problem. Please try again.", listening: "Listening… tap again to stop", working: "Understanding…",
      heard: "Heard", no_catch: "Didn't catch that — try again or type.", mic_denied: "Microphone blocked. Allow it in your browser settings, or type.",
      no_mic: "Voice isn't supported on this browser. Please type.",
      confirm: "Confirm", not_now: "Not now", done_ok: "Done! ", cancelled: "Okay, nothing was sent.",
      problems: "Report a problem", requests_h: "Ask for something", alert_now: "Alert front desk now", call: "Call",
      alert_sent: "The front desk has been alerted. Stay calm; help is coming.",
      chips: ["Wi-Fi?", "Breakfast time?", "Towels please", "Late check-out", "Check-out time?", "Nearby places"],
      express: "Quick check-out", leave_time: "What time will you leave?", luggage: "I'd like help with my bags", book_checkout: "Book quick check-out",
      co_hint: "Check-out is at {t}. Tell us when you leave and we will have everything ready.",
      co_booked: "Quick check-out booked for {t}{l}.", co_lug: " with help for your bags", co_done: "Checked out. Thank you for staying with us!",
      late: "Late check-out", until: "Until", reason: "Reason (if you like)", ask_late: "Ask for late check-out",
      late_hint: "Possible until {t} if the room is free. The manager will say yes or no.", late_none: "Late check-out is not possible here.",
      late_pending: "Asked until {t}. Waiting for the manager.", late_ok: "Yes, you can stay until {t}.", late_no: "Sorry, late check-out until {t} is not possible.",
      feedback: "How was your stay?", comment: "Comment", comment_ph: "Tell us more (if you like)", send_feedback: "Send feedback",
      fb_thanks: "Thank you for your feedback!", bill: "Your bill", bill_est: "Worked out from menu prices", total: "Total (about)",
      bill_note: "Please get your final bill from the front desk.", bill_est_note: "This is only a guide. The front desk has the final bill.",
      wifi: "Wi-Fi", network: "Network", password: "Password", times: "Check-in & check-out", checkin: "Check-in", checkout_t: "Check-out",
      amenities: "Amenities", dining: "Dining menu", policies: "House rules", nearby: "Nearby", faq: "Common questions", contacts: "Call us (dial from the room phone)",
      ext: "ext.", stage_open: "Received", stage_accepted: "Accepted", stage_in_progress: "In progress", stage_done: "Done",
      tooLong: "Recording stopped at 60 seconds.",
      open_maps: "Open in Maps", about_km: "About {d} km", sample: "Sample listing", quiet: "Quieter",
      places_note: "Distances are straight-line and approximate. Check the road and timings before you go.",
      team: { housekeeping: "Housekeeping", fnb_service: "Room service", kitchen: "Kitchen", maintenance: "Maintenance", front_office: "Front desk", security: "Security", generic: "Hotel team" },
    },
    hi: {
      offline: "इंटरनेट नहीं है। इंटरनेट आते ही फिर जुड़ जाएगा।", room: "कमरा",
      ask: "पूछें", explore: "होटल की जानकारी", requests: "मेरी माँगें", checkout: "चेक-आउट", ask_title: "कुछ भी पूछिए",
      voice: "आवाज़ चुनें", ask_us: "हमसे पूछें", what_need: "आपको क्या चाहिए?", voice_menu: "बोलकर जवाब",
      speak_replies: "जवाब बोलकर सुनाएँ", st_idle: "मदद के लिए तैयार", st_listening: "सुन रही हूँ…", st_thinking: "सोच रही हूँ…",
      st_speaking: "बोल रही हूँ…", stop: "बोलना बंद करें", voice_on: "आवाज़ चालू", voice_off: "आवाज़ बंद",
      voice_on_aria: "जवाब आवाज़ में सुनाई देंगे। चुपचाप पढ़ने के लिए दबाएँ।", voice_off_aria: "जवाब आवाज़ में नहीं आएँगे। सुनने के लिए दबाएँ।",
      mic_talk: "बोलने के लिए दबाएँ", mic_stop: "सुन रही हूँ। रोकने के लिए दबाएँ।", thinking: "सोच रही हूँ",
      starters: [["towels", "🧺", "तौलिये", "तौलिये चाहिए"], ["clean", "🧹", "कमरे की सफ़ाई", "कमरे की सफ़ाई करवा दीजिए"],
        ["wifi", "📶", "Wi-Fi", "Wi-Fi का पासवर्ड क्या है?"], ["food", "🍽", "खाना", "खाने का मेन्यू"],
        ["places", "🏞", "आसपास घूमें", "आसपास घूमने की जगह"], ["problem", "🛠", "कमरे में परेशानी", ""]],
      problem_q: "माफ़ कीजिए। क्या परेशानी है? एक चुनिए।", sent_to: "{d} को भेज दिया",
      ai_notice: "कृपया फ़ोन नंबर या कार्ड नंबर जैसी निजी बातें न लिखें।",
      consent: "मेरी आवाज़ को टेक्स्ट बनाने के लिए बाहर की सर्विस को भेजना ठीक है। यह सेव नहीं होती।",
      type_instead: "लिखकर बताएँ", allow_mic: "ठीक है, बोलें", type_here: "अपना संदेश लिखें",
      sub: "जो चाहिए उस पर टैप करें। सही स्टाफ़ को तुरंत पता चलेगा।", quick_requests: "जल्दी माँगें", note: "कुछ और बताना है? (अगर चाहें)",
      status: "आपकी माँगें", none: "अभी कोई माँग नहीं।", sent: "माँग भेज दी गई। टीम को सूचना मिल गई है।",
      privacy: "इमरजेंसी में फ़्रंट डेस्क को कॉल करें।",
      received: "मिल गई", "on the way": "रास्ते में", done: "पूरा", bad: "यह QR कोड काम नहीं कर रहा। फ़्रंट डेस्क को कॉल करें।",
      net: "नेटवर्क की समस्या। फिर कोशिश करें।", listening: "सुन रही हूँ… रोकने के लिए फिर दबाएँ", working: "समझ रही हूँ…",
      heard: "सुना", no_catch: "समझ नहीं आया — फिर बोलें या टाइप करें।", mic_denied: "माइक बंद है। ब्राउज़र सेटिंग में अनुमति दें, या टाइप करें।",
      no_mic: "इस ब्राउज़र में आवाज़ नहीं चलती। कृपया टाइप करें।",
      confirm: "हाँ, भेज दो", not_now: "अभी नहीं", done_ok: "हो गया! ", cancelled: "ठीक है, कुछ नहीं भेजा।",
      problems: "कोई परेशानी बताएँ", requests_h: "कुछ मँगवाएँ", alert_now: "फ़्रंट डेस्क को अभी बताएँ", call: "कॉल करें",
      alert_sent: "मैंने फ़्रंट डेस्क को बता दिया है। घबराइए नहीं, मदद आ रही है।",
      chips: ["Wi-Fi?", "नाश्ता कब है?", "तौलिये चाहिए", "लेट check-out", "check-out कब है?", "आसपास घूमने की जगह"],
      express: "जल्दी check-out", leave_time: "आप कितने बजे निकलेंगे?", luggage: "सामान उठाने में मदद चाहिए", book_checkout: "जल्दी check-out बुक करें",
      co_hint: "Check-out {t} बजे है। बताइए आप कब निकलेंगे, हम सब तैयार रखेंगे।",
      co_booked: "जल्दी check-out {t} बजे बुक है{l}।", co_lug: ", सामान में मदद के साथ", co_done: "Check-out हो गया। हमारे साथ रहने के लिए धन्यवाद!",
      late: "लेट check-out", until: "कब तक", reason: "वजह (अगर चाहें)", ask_late: "लेट check-out माँगें",
      late_hint: "अगर कमरा खाली हो तो {t} बजे तक रुक सकते हैं। मैनेजर हाँ या ना बताएँगे।", late_none: "यहाँ लेट check-out नहीं होता।",
      late_pending: "{t} बजे तक की माँग भेज दी। मैनेजर के जवाब का इंतज़ार है।", late_ok: "हाँ, आप {t} बजे तक रुक सकते हैं।", late_no: "माफ़ कीजिए, {t} बजे तक लेट check-out नहीं हो पाएगा।",
      feedback: "आपका स्टे कैसा रहा?", comment: "आपकी बात", comment_ph: "और बताइए (अगर चाहें)", send_feedback: "फ़ीडबैक भेजें",
      fb_thanks: "आपके फ़ीडबैक के लिए धन्यवाद!", bill: "आपका बिल", bill_est: "मेन्यू के दामों से जोड़ा गया", total: "कुल (लगभग)",
      bill_note: "पूरा बिल फ़्रंट डेस्क से लें।", bill_est_note: "यह सिर्फ़ अंदाज़ा है। पूरा बिल फ़्रंट डेस्क देगा।",
      wifi: "Wi-Fi", network: "नेटवर्क", password: "पासवर्ड", times: "चेक-इन और चेक-आउट", checkin: "चेक-इन", checkout_t: "चेक-आउट",
      amenities: "सुविधाएँ", dining: "खाने का मेन्यू", policies: "होटल के नियम", nearby: "आसपास", faq: "सवाल-जवाब", contacts: "कॉल करें (कमरे के फ़ोन से)",
      ext: "एक्सटेंशन", stage_open: "मिल गई", stage_accepted: "स्टाफ़ ने ले लिया", stage_in_progress: "काम जारी", stage_done: "पूरा",
      tooLong: "60 सेकंड पर रिकॉर्डिंग रुक गई।",
      open_maps: "मैप में खोलें", about_km: "लगभग {d} km", sample: "नमूना जानकारी", quiet: "कम भीड़",
      places_note: "दूरी सीधी लाइन में और अंदाज़े से है। जाने से पहले रास्ता और समय पता कर लें।",
      team: { housekeeping: "हाउसकीपिंग", fnb_service: "रूम सर्विस", kitchen: "किचन", maintenance: "मेंटेनेंस", front_office: "फ़्रंट डेस्क", security: "सिक्योरिटी", generic: "होटल टीम" },
    },
  };
  const S = {
    lang: store.get("hoi.guest.lang") === "hi" ? "hi" : "en", data: null, history: [], muted: !!(window.HOIVoice && window.HOIVoice.muted),
    consent: store.get("hoi.guest.voice_consent") === "1", tab: "ask", rating: 0, rec: null, pendingMic: null, lastReqSig: "",
    started: false, thinking: false, speaking: false,
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
  $("#photoCredit").addEventListener("click", (e) => { if (e.currentTarget.title) toast(e.currentTarget.title); });
  $("#hotelLogo").addEventListener("error", () => { $("#logoPlate").classList.add("hidden"); $("#hotel").classList.remove("hidden"); });
  const NEUTRAL_MARK = "/shared/brand/hotel-mark.svg";
  $("#aMark").addEventListener("error", () => { if ($("#aMark").getAttribute("src") !== NEUTRAL_MARK) $("#aMark").src = NEUTRAL_MARK; });
  const token = new URLSearchParams(location.search).get("t") || "";
  const base = `/public/guest/${encodeURIComponent(token)}`;
  const tr = (k) => (T[S.lang] || T.en)[k] ?? T.en[k] ?? k;
  const fmt = (k, o) => tr(k).replace(/\{(\w)\}/g, (_, x) => o[x] ?? "");

  // ---------------------------------------------------------------- api
  async function api(method, path, body, isForm) {
    const opts = { method, headers: {} };
    if (body !== undefined) { if (isForm) opts.body = body; else { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); } }
    let r;
    // /shared/net.js: "waking up the server" pill after ~4 s on a sleeping server, and one retry (network error / 502 / 503)
    try { r = await window.HOINet.fetch(base + path, opts); } catch (e) { const err = new Error(tr("net")); err.status = 0; throw err; }
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
    paintVoiceToggle(); status();
    $("#chips").innerHTML = tr("chips").map((c) => `<button type="button" class="chip-btn" data-chip="${esc(c)}">${esc(c)}</button>`).join("");
    $("#wgrid").innerHTML = tr("starters").map(([k, ico, label, say]) =>
      `<button type="button" class="wbtn" data-starter="${esc(k)}" data-say="${esc(say)}"><span class="wico" aria-hidden="true">${ico}</span><span>${esc(label)}</span></button>`).join("");
    if (!S.data) return;
    const d = S.data, p = d.profile || {};
    $("#hotel").textContent = p.display_name || d.hotel;
    paintLogo(window.HOI_SAFE_IMG(p.logo_url), p.display_name || d.hotel);
    paintMark(window.HOI_SAFE_IMG(p.logo_url));
    paintCover(window.HOI_SAFE_IMG(p.cover_photo_url), p.cover_photo_credit || "");
    $("#roomNo").textContent = d.room;
    $("#welcome").textContent = p.welcome || "";
    // The header already welcomes the guest: the chat starts with the quick buttons ("What do you need?"), no greeting bubble.
    paintMenu(); paintRequests(); paintExplore(); paintCheckout();
  }

  // Voice replies: the speaker button shows on / off and opens a small menu (read aloud on/off + choose the voice).
  // The choices are kept on this device by /shared/voice.js.
  function paintVoiceToggle() {
    const on = !S.muted;
    $("#muteIco").textContent = on ? "🔊" : "🔇";
    $("#muteTxt").textContent = tr(on ? "voice_on" : "voice_off");
    $("#mute").setAttribute("aria-label", tr(on ? "voice_on_aria" : "voice_off_aria"));
    $("#mute").classList.toggle("off", !on);
    $("#voiceOn").checked = on;
    $("#voiceRow").classList.toggle("hidden", !S.voices || !on);
  }
  function voiceMenu(open) {
    $("#voiceMenu").classList.toggle("hidden", !open);
    $("#mute").setAttribute("aria-expanded", open ? "true" : "false");
  }

  // Assistant status in the bar: listening > thinking > speaking > ready. Also drives the Stop button.
  function status() {
    const st = S.rec ? "listening" : S.thinking ? "thinking" : S.speaking ? "speaking" : "idle";
    $("#abar").dataset.state = st;
    $("#aStatus").textContent = tr("st_" + st);
    $("#stopSpeak").classList.toggle("hidden", !S.speaking);
    $("#mic").setAttribute("aria-label", tr(S.rec && S.rec.target === "chat" ? "mic_stop" : "mic_talk"));
  }
  function stopSpeaking() { if (window.HOIVoice) window.HOIVoice.stop(); S.speaking = false; status(); }

  // The assistant bar shows the hotel's own square mark: the logo's "-mark" sibling (himsagar-logo.svg -> himsagar-mark.svg),
  // else a neutral hotel icon (also when the mark file is missing).
  function paintMark(logo) {
    const mark = logo && /-logo\.\w+$/.test(logo) ? logo.replace(/-logo(\.\w+)$/, "-mark$1") : NEUTRAL_MARK;
    if ($("#aMark").getAttribute("src") !== mark) $("#aMark").src = mark;
  }

  // Hotel logo on a white plate (keeps the brand colours readable on the orange header); hotel name text otherwise.
  function paintLogo(url, name) {
    const img = $("#hotelLogo"), plate = $("#logoPlate");
    if (!url) { plate.classList.add("hidden"); $("#hotel").classList.remove("hidden"); return; }
    img.alt = name || "";
    if (img.getAttribute("src") !== url) img.src = url;
    plate.classList.remove("hidden"); $("#hotel").classList.add("hidden");
  }

  // Property photo behind the header (licensed photo of the area; credit in a small (i) tooltip, not a caption).
  function paintCover(url, credit) {
    const hero = $("#hero");
    if (!url) { hero.classList.remove("photo"); hero.style.backgroundImage = ""; $("#photoCredit").classList.add("hidden"); return; }
    hero.classList.add("photo");
    hero.style.backgroundImage = `linear-gradient(180deg,rgba(10,20,40,.35),rgba(10,20,40,.78)),url("${url}")`;
    const pc = $("#photoCredit"); pc.title = credit ? "Photo: " + credit : ""; pc.setAttribute("aria-label", credit ? "Photo: " + credit : "Photo credit"); pc.classList.toggle("hidden", !credit);
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
    // Live status on the request cards in the chat ("Sent to Housekeeping · 14:05 · on the way").
    $$(".confirm[data-rid]").forEach((card) => {
      const r = reqs.find((q) => q.id === card.dataset.rid);
      if (r) card.querySelector(".rmeta").innerHTML = reqMeta(r);
    });
  }
  const STAGE_WORD = { open: "received", accepted: "on the way", in_progress: "on the way", done: "done" };
  function reqMeta(r) {
    const team = (T[S.lang].team || T.en.team)[reqDept(r)] || T.en.team.generic;
    const stage = STAGE_WORD[r.stage] || "received";
    return `<span class="rtick" aria-hidden="true">✓</span><span>${esc(fmt("sent_to", { d: team }))} · ${esc((r.at || "").slice(11, 16))}</span>` +
      `<span class="rstage ${esc(r.stage || "open")}">${esc(tr(stage))}</span>`;
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
      $("#bill").innerHTML = `<p class="muted">${esc(tr("bill_note"))}</p>` + (rows ? `<div class="eyebrow">${esc(tr("bill_est"))}</div>${rows}<div class="est"><b>${esc(tr("total"))}</b><b>₹${esc(b.estimate_total_inr)}</b></div><p class="muted">${esc(tr("bill_est_note"))}</p>` : "");
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
  // Before the first question the page stays at the top (welcome + starters); after it, the newest message is kept in view.
  const smooth = () => (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");
  function scrollThread() { if (S.started) requestAnimationFrame(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: smooth() })); }
  function begin() { if (S.started) return; S.started = true; $("#starter").classList.add("hidden"); $("#chips").classList.remove("hidden"); }
  function me(text, cls) { begin(); const el = document.createElement("div"); el.className = "msg " + (cls || "me"); el.textContent = text; $("#thread").appendChild(el); scrollThread(); return el; }
  // "Problem in room": the problem list from the hotel's request menu, as big buttons; a tap asks the assistant.
  function problemPicker() {
    begin();
    const PROBLEM_KEYS = ["ac", "hot_water", "electrical"];
    const menu = (S.data && S.data.menu) || [];
    const list = menu.filter((m) => m.group === "problem" || PROBLEM_KEYS.includes(m.key)).slice(0, 9);
    const other = menu.find((m) => m.key === "other");
    if (other) list.push(other);
    bot(tr("problem_q"), null, S.lang, true);
    const wrap = document.createElement("div"); wrap.className = "pickgrid";
    wrap.innerHTML = list.map((m) => { const l = S.lang === "hi" ? m.label_hi : m.label; return `<button type="button" class="pick${m.urgent ? " urgent" : ""}" data-chip="${esc(l)}">${esc(l)}</button>`; }).join("");
    $("#thread").appendChild(wrap); scrollThread();
  }
  // Place cards (places to visit): picture, name, one-line tip, distance, "quieter" reason, Open in Maps. Fixed-size
  // picture boxes so nothing jumps while images load. Only Google Maps search links are accepted.
  const MAPS_RE = /^https:\/\/www\.google\.com\/maps\/search\/\?api=1&query=[^\s"'<>]+$/;
  function placeCards(cards) {
    const wrap = document.createElement("div"); wrap.className = "places";
    wrap.innerHTML = cards.slice(0, 6).map((c) => {
      const img = window.HOI_SAFE_IMG(c.image) || "/shared/places/mountain.svg";
      const url = MAPS_RE.test(c.maps_url || "") ? c.maps_url : "";
      const dist = c.distance_km != null ? fmt("about_km", { d: c.distance_km }) : (c.distance_note || "");
      const quiet = c.offbeat ? ((S.lang === "hi" && c.why_quiet_hi) || c.why_quiet || tr("quiet")) : "";
      return `<article class="place"><img class="pimg" src="${esc(img)}" alt="" width="88" height="88" loading="lazy" decoding="async">` +
        `<div class="pbody"><b class="pname">${esc(c.name)}</b>${c.tip ? `<p class="ptip">${esc(c.tip)}</p>` : ""}` +
        `<div class="pmeta">${dist ? `<span class="pchip">${esc(dist)}</span>` : ""}${quiet ? `<span class="pchip quiet">${esc(quiet)}</span>` : ""}` +
        `${c.sample ? `<span class="pchip">${esc(tr("sample"))}</span>` : ""}</div></div>` +
        (url ? `<a class="pmap" href="${esc(url)}" target="_blank" rel="noopener noreferrer">📍 ${esc(tr("open_maps"))}</a>` : "") + `</article>`;
    }).join("") + `<p class="pnote">${esc(tr("places_note"))}</p>`;
    return wrap;
  }
  function bot(text, action, lang, silent, extra) {
    const el = document.createElement("div"); el.className = "msg bot"; el.textContent = text; $("#thread").appendChild(el);
    const cards = (extra && Array.isArray(extra.cards)) ? extra.cards : [];
    if (cards.length) $("#thread").appendChild(placeCards(cards));
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
    if (!silent) speak((extra && extra.speak) || text, lang);  // cards: only the short sentence is read out, never the list or links
  }
  function typing(on) {
    let el = $("#typing");
    if (on && !el) { el = document.createElement("div"); el.id = "typing"; el.className = "msg bot typing"; el.innerHTML = `<span class="sr">${esc(tr("thinking"))}</span><i aria-hidden="true"></i><i aria-hidden="true"></i><i aria-hidden="true"></i>`; $("#thread").appendChild(el); scrollThread(); }
    if (!on && el) el.remove();
    S.thinking = !!on; status();
  }
  async function send(text) {
    text = (text || "").trim().slice(0, 500);
    if (!text) return;
    stopSpeaking();  // a new question always silences the previous answer
    $$(".pickgrid").forEach((g) => g.remove());
    me(text);
    typing(true);
    try {
      const r = await api("POST", "/chat", { message: text, lang: S.lang, history: S.history.slice(-6) });
      typing(false);
      S.history.push({ role: "user", text }, { role: "assistant", text: r.reply });
      S.history = S.history.slice(-6);
      bot(r.reply, r.proposed_action, r.lang, false, { cards: r.cards, speak: r.speak });
    } catch (e) { typing(false); bot(e.message, null, null, true); }
  }
  async function confirmAction(card, yes) {
    const action = card._action;
    card.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    if (!yes) { card.remove(); bot(tr("cancelled"), null, S.lang); return; }
    try {
      const params = { ...action.params };
      if (action.action === "feedback") params.lang = S.lang;
      const res = await api("POST", "/actions", { action: action.action, params });
      card.classList.add("done");
      const row = card.querySelector(".row") || card.querySelector(".alert");
      if (row) row.remove();
      const newest = action.action === "request" && res && Array.isArray(res.requests) ? res.requests[0] : null;
      if (newest) {  // the new request is first (newest first); its status on this card follows the live request list
        card.dataset.rid = newest.id;
        const m = document.createElement("div"); m.className = "rmeta"; m.innerHTML = reqMeta(newest); card.appendChild(m);
      }
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
    S.voices = n;
    paintVoiceToggle();
  }
  window.addEventListener("hoivoice", (e) => { S.speaking = !!(e.detail && e.detail.speaking); status(); });

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
  // Mic level: a ring around the mic grows with the voice (Web Audio analyser). Off when the guest prefers less motion.
  function meter(stream) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC || (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches)) return null;
    try {
      const ctx = new AC(), an = ctx.createAnalyser(); an.fftSize = 256;
      ctx.createMediaStreamSource(stream).connect(an);
      const buf = new Uint8Array(an.fftSize), mic = $("#mic");
      const m = { ctx, raf: 0 };
      const tick = () => {
        an.getByteTimeDomainData(buf);
        let sum = 0; for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
        mic.style.setProperty("--lvl", Math.min(1, Math.sqrt(sum / buf.length) * 4).toFixed(2));
        m.raf = requestAnimationFrame(tick);
      };
      tick();
      return m;
    } catch (e) { return null; }
  }
  function meterOff(m) {
    $("#mic").style.setProperty("--lvl", "0");
    if (!m) return;
    cancelAnimationFrame(m.raf);
    try { m.ctx.close(); } catch (e) { /* closed */ }
  }
  async function startRec(target) {
    if (S.rec) { stopRec(); return; }
    stopSpeaking();  // tapping the mic always silences the assistant first
    if (!navigator.mediaDevices || !window.MediaRecorder) { micState(tr("no_mic")); return; }
    if (needConsent(() => startRec(target))) return;
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (e) { micState(tr("mic_denied")); return; }
    const mime = pickMime();
    let rec;
    try { rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream); } catch (e) { stream.getTracks().forEach((t) => t.stop()); micState(tr("no_mic")); return; }
    const chunks = [];
    const t0 = Date.now();
    const lvl = target === "chat" ? meter(stream) : null;
    S.rec = { rec, stream, target, timer: setTimeout(() => { micState(tr("tooLong")); stopRec(); }, MAX_REC_S * 1000) };
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = async () => {
      meterOff(lvl);
      stream.getTracks().forEach((t) => t.stop());
      const btn = target === "fb" ? $("#fbMic") : $("#mic");
      btn.classList.remove("rec"); btn.classList.add("busy");
      micState(tr("working"));
      if (target === "chat") { S.thinking = true; status(); }
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
      finally { btn.classList.remove("busy"); if (target === "chat" && !$("#typing")) { S.thinking = false; status(); } }
    };
    rec.start();
    (target === "fb" ? $("#fbMic") : $("#mic")).classList.add("rec");
    micState(tr("listening"));
    stopSpeaking(); status();
  }
  function stopRec() {
    if (!S.rec) return;
    clearTimeout(S.rec.timer);
    const { rec } = S.rec; S.rec = null;
    try { rec.stop(); } catch (e) { /* already stopped */ }
    status();
  }

  // ---------------------------------------------------------------- events
  document.addEventListener("click", async (e) => {
    const l = e.target.closest("[data-lang]");
    if (l) { S.lang = l.dataset.lang; store.set("hoi.guest.lang", S.lang); micState(""); paint(); fillVoices(); return; }
    const tb = e.target.closest("[data-tab]");
    if (tb) { show(tb.dataset.tab); return; }
    const chip = e.target.closest("[data-chip]");
    if (chip) { send(chip.dataset.chip); return; }
    const st = e.target.closest("[data-starter]");
    if (st) { if (st.dataset.starter === "problem") { stopSpeaking(); problemPicker(); } else send(st.dataset.say); return; }
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
  $("#mute").addEventListener("click", (e) => { e.stopPropagation(); voiceMenu($("#voiceMenu").classList.contains("hidden")); });
  $("#voiceOn").addEventListener("change", () => {
    S.muted = !$("#voiceOn").checked;
    if (window.HOIVoice) window.HOIVoice.setMuted(S.muted);  // muting also stops the current reply
    if (S.muted) stopSpeaking();
    paintVoiceToggle();
  });
  // The menu closes on a tap outside it or on Esc (Esc first closes the menu, then stops speaking).
  document.addEventListener("click", (e) => { if (!e.target.closest("#voiceMenu, #mute")) voiceMenu(false); }, true);
  $("#stopSpeak").addEventListener("click", () => { stopSpeaking(); $("#msg").focus({ preventScroll: true }); });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!$("#voiceMenu").classList.contains("hidden")) { e.preventDefault(); voiceMenu(false); $("#mute").focus(); return; }
    if (S.speaking) { e.preventDefault(); stopSpeaking(); }
  });
  // Leaving the page (another app, tab switch, screen off) silences the assistant.
  document.addEventListener("visibilitychange", () => { if (document.hidden) { stopSpeaking(); stopRec(); } });
  window.addEventListener("pagehide", () => { stopSpeaking(); stopRec(); });
  // Keep the input above the on-screen keyboard: hide the tab bar while typing, and on browsers whose keyboard
  // overlays the page (iOS Safari), lift the dock by the covered height.
  $("#msg").addEventListener("focus", () => document.body.classList.add("kb"));
  $("#msg").addEventListener("blur", () => setTimeout(() => { if (document.activeElement !== $("#msg")) document.body.classList.remove("kb"); }, 120));
  if (window.visualViewport) {
    const vv = window.visualViewport;
    const lift = () => { const h = Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop)); document.documentElement.style.setProperty("--kb", h + "px"); };
    vv.addEventListener("resize", lift); vv.addEventListener("scroll", lift);
  }
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
