// Guest request page: the room's QR code carries a random token (?t=...). No login, no personal data.
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const T = {
    en: { hello: "How can we help?", room: "Room", sub: "Tap a request. The right team member is notified at once.", note: "Anything to add? (optional)",
          status: "Your requests today", none: "No requests yet.", sent: "Request sent. Someone is on the way.",
          privacy: "We don't ask for your name or phone number. For emergencies, call the front desk.",
          received: "received", "on the way": "on the way", done: "done", bad: "This QR code is not valid. Please call the front desk." },
    hi: { hello: "हम कैसे मदद करें?", room: "कमरा", sub: "एक विकल्प चुनें। सही स्टाफ़ को तुरंत सूचना मिलेगी।", note: "कुछ और बताना है? (वैकल्पिक)",
          status: "आज की आपकी माँगें", none: "अभी कोई माँग नहीं।", sent: "माँग भेज दी गई। कोई आ रहा है।",
          privacy: "हम आपका नाम या फ़ोन नंबर नहीं माँगते। आपात स्थिति में फ़्रंट डेस्क को कॉल करें।",
          received: "मिल गई", "on the way": "रास्ते में", done: "पूरा", bad: "यह QR कोड मान्य नहीं है। फ़्रंट डेस्क को कॉल करें।" },
  };
  let lang = localStorage.getItem("hoi.guest.lang") || "en", data = null;
  const token = new URLSearchParams(location.search).get("t") || "";
  const tr = (k) => (T[lang] || T.en)[k] || k;

  function paint() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-t]").forEach((el) => { el.textContent = tr(el.dataset.t); });
    document.querySelectorAll("[data-lang]").forEach((b) => b.classList.toggle("on", b.dataset.lang === lang));
    if (!data) return;
    $("#hotel").textContent = data.hotel;
    $("#roomNo").textContent = data.room;
    $("#menu").innerHTML = data.menu.map((m) =>
      `<button class="opt" data-key="${esc(m.key)}">${esc(lang === "hi" ? m.label_hi : m.label)}<small>${esc(lang === "hi" ? m.label : m.label_hi)}</small></button>`).join("");
    const tone = { received: "watch", "on the way": "watch", done: "low" };
    $("#list").innerHTML = data.requests.length ? data.requests.map((r) =>
      `<div class="st"><span>${esc(r.title)}<br><span class="muted">${esc(r.at.slice(11, 16))}</span></span><span class="chip ${tone[r.status] || "gray"}">${esc(tr(r.status))}</span></div>`).join("")
      : `<p class="muted">${esc(tr("none"))}</p>`;
  }

  function fail(msg) { $("#err").textContent = msg; $("#err").classList.remove("hidden"); }

  async function load() {
    try {
      const r = await fetch(`/public/guest/${encodeURIComponent(token)}`);
      if (!r.ok) { fail(tr("bad")); return; }
      data = await r.json(); paint();
    } catch (e) { fail("Network problem. Please try again."); }
  }

  document.addEventListener("click", async (e) => {
    const l = e.target.closest("[data-lang]");
    if (l) { lang = l.dataset.lang; localStorage.setItem("hoi.guest.lang", lang); paint(); return; }
    const b = e.target.closest("[data-key]");
    if (!b) return;
    document.querySelectorAll(".opt").forEach((x) => { x.disabled = true; });
    $("#err").classList.add("hidden");
    try {
      const r = await fetch(`/public/guest/${encodeURIComponent(token)}/requests`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: b.dataset.key, note: $("#note").value }),
      });
      const j = await r.json();
      if (!r.ok) { fail(typeof j.detail === "string" ? j.detail : "Could not send."); }
      else { data = j; $("#note").value = ""; paint(); const ok = document.createElement("div"); ok.className = "banner blue"; ok.textContent = tr("sent"); $("#menu").before(ok); setTimeout(() => ok.remove(), 3000); }
    } catch (err) { fail("Network problem. Please try again."); }
    finally { document.querySelectorAll(".opt").forEach((x) => { x.disabled = false; }); }
  });

  if (!token) fail(tr("bad")); else load();
  setInterval(() => { if (token && data) load(); }, 15000);
})();
