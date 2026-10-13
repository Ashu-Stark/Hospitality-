// HOI spoken replies, shared by the guest concierge and the staff app (no build step, strict CSP).
// Layer 1 (always): browser speechSynthesis with ranked voices: a soft female voice with an Indian accent
//   (hi-IN natural voices such as Microsoft Swara / Kalpana / "Google हिन्दी"; en-IN such as Neerja / Heera;
//   male names de-prioritised), rate 0.92, pitch 1.05, volume 0.9, spoken sentence by sentence so it can be stopped.
// Layer 2 (optional): server voice (Sarvam Bulbul) via a caller-supplied fetcher; a 204 means "use layer 1".
// Text is normalised first (times, rupees, numbers in Hindi words); the same rules live in services/speech_text.py.
(() => {
  "use strict";
  const HI_0_99 = "शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे".split(" ");
  const EN_0_19 = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(" ");
  const EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty"];
  const TIME = "([01]?\\d|2[0-3])[:.]([0-5]\\d)";
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };

  function hiNumber(n) {
    if (n < 100) return HI_0_99[n];
    const parts = [];
    for (const [size, word] of [[100000, "लाख"], [1000, "हज़ार"], [100, "सौ"]]) {
      if (n >= size) { parts.push(hiNumber(Math.floor(n / size)) + " " + word); n %= size; }
    }
    if (n) parts.push(HI_0_99[n]);
    return parts.join(" ");
  }
  const hiHour = (h) => HI_0_99[h % 12 || 12];
  function hiTime(h, m) {
    const period = h >= 12 && h < 16 ? "दोपहर " : h >= 16 && h < 20 ? "शाम " : (h >= 20 || h < 4) ? "रात " : "";
    let core;
    if (m === 0) core = hiHour(h) + " बजे";
    else if (m === 30) core = ({ 1: "डेढ़ बजे", 2: "ढाई बजे" })[h % 12] || "साढ़े " + hiHour(h) + " बजे";
    else if (m === 15) core = "सवा " + hiHour(h) + " बजे";
    else if (m === 45) core = "पौने " + hiHour(h + 1) + " बजे";
    else core = hiHour(h) + " बजकर " + HI_0_99[m] + " मिनट";
    return period + core;
  }
  const enSmall = (n) => (n < 20 ? EN_0_19[n] : EN_TENS[Math.floor(n / 10)] + (n % 10 ? "-" + EN_0_19[n % 10] : ""));
  function enTime(h, m) {
    const h12 = h % 12 || 12;
    if (m === 0) return h === 12 ? "twelve noon" : h < 12 ? enSmall(h12) + " o'clock" : enSmall(h12) + " p.m.";
    return enSmall(h12) + " " + (m < 10 ? "oh " + enSmall(m) : enSmall(m)) + (h >= 12 ? " p.m." : "");
  }

  function normalize(text, lang) {
    const hi = lang === "hi";
    const tf = hi ? hiTime : enTime;
    let t = String(text || "").replace(/[०-९]/g, (d) => String("०१२३४५६७८९".indexOf(d)));
    t = t.replace(/[\u{1F000}-\u{1FAFF}☀-➿️‍]/gu, "").replace(/[*_#`>~|]+/g, " ");
    t = t.replace(new RegExp(TIME + "\\s*[-–]\\s*" + TIME, "g"), (_, a, b, c, d) => {
      const x = tf(+a, +b), y = tf(+c, +d);
      return hi ? `${x} से ${y} तक` : `${x} to ${y}`;
    });
    t = t.replace(new RegExp("(^|[^\\d:])" + TIME + "(?![\\d:])", "g"), (_, pre, h, m) => pre + tf(+h, +m));
    if (hi) {
      t = t.replace(/(?:₹|rs\.?|inr)\s*(\d[\d,]*)/gi, (_, n) => hiNumber(+n.replace(/,/g, "")) + " रुपये");
      t = t.replace(/(\d[\d,]*)\s*(?:₹|rupees|rs\.?|inr)/gi, (_, n) => hiNumber(+n.replace(/,/g, "")) + " रुपये");
      t = t.replace(/\bext\.?\s*/gi, "एक्सटेंशन ");
      t = t.replace(/\d{1,7}/g, (n) => hiNumber(+n));
      t = t.split("Wi-Fi").join("वाई-फ़ाई");
      t = t.replace(/बजे\s+बजे/g, "बजे").replace(/तक\s+तक/g, "तक");
    } else {
      t = t.replace(/(?:₹|rs\.?|inr)\s*(\d[\d,]*)/gi, "$1 rupees").replace(/\bext\.\s*/gi, "extension ");
    }
    return t.replace(/\s+/g, " ").trim();
  }
  const sentences = (t) => t.replace(/([।.?!])\s+/g, "$1\n").split("\n").map((s) => s.trim()).filter(Boolean);

  // ---------------------------------------------------------------- voices
  const FEMALE = ["swara", "kalpana", "heera", "neerja", "lekha", "aditi", "veena", "priya", "female", "google हिन्दी", "google hindi", "zira", "samantha"];
  const MALE = ["madhur", "hemant", "ravi", "prabhat", "prakash", "male", "rishi", "david", "mark", "guy"];
  const NATURAL = ["natural", "neural", "online"];
  const hasSynth = () => "speechSynthesis" in window && typeof window.SpeechSynthesisUtterance === "function";
  const all = () => (hasSynth() ? window.speechSynthesis.getVoices() : []);
  const voiceLang = (lang) => (lang === "hi" ? "hi" : "en");  // Hinglish (Latin letters) reads best with an Indian-English voice

  function score(v, want) {
    const name = (v.name || "").toLowerCase(), l = (v.lang || "").toLowerCase().replace("_", "-");
    let s = 0;
    if (want === "hi") { if (!l.startsWith("hi")) return -1; s += 100; }
    else { if (!l.startsWith("en")) return -1; s += l === "en-in" ? 100 : (l === "en-gb" ? 20 : 10); }
    if (FEMALE.some((w) => name.includes(w))) s += 40;
    if (MALE.some((w) => new RegExp("(^|\\W)" + w + "(\\W|$)").test(name))) s -= 60;
    if (NATURAL.some((w) => name.includes(w))) s += 25;
    if (name.includes("google")) s += 8;
    if (v.localService === false) s += 2;
    return s;
  }
  function ranked(lang) {
    const want = voiceLang(lang);
    return all().map((v) => [score(v, want), v]).filter(([s]) => s >= 0).sort((a, b) => b[0] - a[0]).map(([, v]) => v);
  }
  function pick(lang) {
    const list = ranked(lang);
    const saved = store.get("hoi.voice." + voiceLang(lang));
    return list.find((v) => v.name === saved) || list[0] || null;
  }
  let ready = null;
  function whenReady() {
    if (!hasSynth()) return Promise.resolve();
    if (all().length) return Promise.resolve();
    if (!ready) {
      ready = new Promise((res) => {
        const done = () => res();
        window.speechSynthesis.addEventListener("voiceschanged", done, { once: true });
        setTimeout(done, 1500);
      });
    }
    return ready;
  }

  // ---------------------------------------------------------------- speaking
  // Pages follow the speaking state through the "hoivoice" window event (detail: {speaking: true|false}) or
  // HOIVoice.speaking, e.g. to show a Stop button. It turns on as soon as a reply is queued (also while the server
  // voice is being fetched) and off when the last sentence ends, on stop(), on mute or on an error.
  const S = { muted: store.get("hoi.voice.mute") === "1", audio: null, gen: 0, serverOff: false, speaking: false, watch: null };
  function setSpeaking(on) {
    on = !!on;
    if (!on && S.watch) { clearInterval(S.watch); S.watch = null; }
    if (on === S.speaking) return;
    S.speaking = on;
    try { window.dispatchEvent(new CustomEvent("hoivoice", { detail: { speaking: on } })); } catch (e) { /* old browser */ }
  }
  function stop() {
    S.gen++;
    if (hasSynth()) { try { window.speechSynthesis.cancel(); } catch (e) { /* ignore */ } }
    if (S.audio) { try { S.audio.pause(); URL.revokeObjectURL(S.audio.src); } catch (e) { /* ignore */ } S.audio = null; }
    setSpeaking(false);
  }
  async function speak(text, lang, opts) {
    stop();
    if (S.muted || !text) return;
    const gen = S.gen;
    const done = () => { if (gen === S.gen) setSpeaking(false); };
    setSpeaking(true);
    const fetcher = opts && opts.server;
    if (fetcher && !S.serverOff) {
      try {
        const blob = await fetcher(String(text).slice(0, 500), lang);
        if (gen !== S.gen) return;
        if (blob && blob.size) {
          const a = new Audio(URL.createObjectURL(blob));
          a.volume = 0.9; S.audio = a;
          a.onended = () => { URL.revokeObjectURL(a.src); if (S.audio === a) S.audio = null; done(); };
          a.onerror = done;
          try { await a.play(); } catch (e) { done(); }
          return;
        }
        S.serverOff = true;  // 204: the server has no voice configured; use the browser for the rest of the session
      } catch (e) { /* fall through to the browser voice */ }
    }
    if (!hasSynth()) { done(); return; }  // text only, silently
    await whenReady();
    if (gen !== S.gen) return;
    const v = pick(lang);
    if (!v) { done(); return; }  // no voice for this language (e.g. no Hindi voice installed): text only, silently
    const parts = sentences(normalize(text, voiceLang(lang) === "hi" ? "hi" : "en"));
    if (!parts.length) { done(); return; }
    parts.forEach((part, i) => {
      const u = new SpeechSynthesisUtterance(part);
      if (v) u.voice = v;
      u.lang = v ? v.lang : (voiceLang(lang) === "hi" ? "hi-IN" : "en-IN");
      u.rate = 0.92; u.pitch = 1.05; u.volume = 0.9;
      u.onerror = done;
      if (i === parts.length - 1) u.onend = done;
      window.speechSynthesis.speak(u);
    });
    // Some browsers drop the last "end" event: when the engine has been idle for two checks in a row, call it finished.
    let idle = 0;
    S.watch = setInterval(() => {
      if (gen !== S.gen) { clearInterval(S.watch); S.watch = null; return; }
      idle = window.speechSynthesis.speaking || window.speechSynthesis.pending ? 0 : idle + 1;
      if (idle >= 2) done();
    }, 700);
  }  function setMuted(m) { S.muted = !!m; store.set("hoi.voice.mute", S.muted ? "1" : "0"); if (S.muted) stop(); }

  // A <select> listing the ranked voices for one language; the choice is remembered on this device.
  async function fillPicker(select, lang) {
    if (!select) return;
    await whenReady();
    const list = ranked(lang), cur = pick(lang);
    select.innerHTML = "";
    list.forEach((v) => {
      const o = document.createElement("option");
      o.value = v.name; o.textContent = `${v.name} (${v.lang})`;
      if (cur && v.name === cur.name) o.selected = true;
      select.appendChild(o);
    });
    select.disabled = !list.length;
    select.onchange = () => { store.set("hoi.voice." + voiceLang(lang), select.value); speak(lang === "hi" ? "नमस्ते, मैं आपकी कैसे मदद करूँ?" : "Hello, how can I help you?", lang); };
    return list.length;
  }

  window.HOIVoice = {
    normalize, sentences, speak, stop, fillPicker, whenReady,
    get muted() { return S.muted; }, setMuted,
    get speaking() { return S.speaking; },
    voices: (lang) => ranked(lang).map((v) => ({ name: v.name, lang: v.lang })),
    chosen: (lang) => { const v = pick(lang); return v ? v.name : null; },
  };
})();
