"""Worker voice commands (docs/HOSPITALITY_SUITE.md section 3): text (typed or transcribed) -> intent + spoken reply.

Rule-based and deterministic (English, Hindi Devanagari, Hinglish): fast, offline, and it never guesses a job.
Nothing happens on /me/voice/command; actions run only through /me/voice/act after the worker confirms, and reuse the
dispatch service (accept / decline / start with the same checks as the buttons). "Done" is never executed by voice:
the after-photo is still required, so the reply routes the worker to the photo flow.
"""

from __future__ import annotations

import re

from .. import mongo
from . import concierge, dispatch, issues, tenants
from .errors import Invalid, NotFound

URGENT = ("urgent", "jaldi", "turant", "abhi", "emergency", "ज़रूरी", "जरूरी", "जल्दी", "तुरंत", "fast", "asap")
WORDS = {
    "accept": (
        "accept",
        "yes",
        "haan",
        "han ",
        "ha ",
        "ok ",
        "okay",
        "le leta",
        "le liya",
        "le lunga",
        "main jaata",
        "main jata",
        "स्वीकार",
        "हाँ",
        "हां",
        "ले लिया",
        "ले लेता",
        "मंज़ूर",
        "मंजूर",
        "theek hai",
        "ठीक है",
    ),
    "decline": ("decline", "reject", "no ", "nahi", "nahin", "mana", "can't", "cannot", "busy", "मना", "नहीं", "नही", "व्यस्त"),
    "done": ("done", "finished", "complete", "ho gaya", "ho gya", "khatam", "kar diya", "हो गया", "ख़त्म", "खत्म", "पूरा", "कर दिया"),
    "start": ("start", "begin", "shuru", "chalu", "शुरू", "चालू"),
    "next": ("next", "what's", "whats", "what is", "my job", "any job", "agla", "kya hai", "kaam", "job", "अगला", "काम", "क्या है"),
    "shift": ("shift", "duty", "roster", "शिफ़्ट", "शिफ्ट", "ड्यूटी"),
    "help": ("help", "madad", "मदद", "kya bol", "क्या बोल"),
    "issue": (
        "report",
        "problem",
        "issue",
        "broken",
        "leak",
        "leaking",
        "kharab",
        "खराब",
        "ख़राब",
        "not working",
        "kaam nahi",
        "काम नहीं",
        "toota",
        "टूटा",
        "टूट",
    ),
}


def _t(lang: str, en: str, hi: str) -> str:
    return hi if lang in ("hi", "hinglish") else en


def _jobs(tid: str, emp: str) -> tuple[dict | None, list[dict]]:
    rows = dispatch.list_jobs(tid, worker=emp)
    offer = next((j for j in rows if j["status"] == "offered" and j.get("offer_to") == emp), None)
    active = [j for j in rows if j["status"] in ("accepted", "in_progress") and j.get("assigned_to") == emp]
    return offer, active


def _title(j: dict) -> str:
    return j["title"].split(" · ")[0]


def _room_txt(j: dict, lang: str) -> str:
    return (_t(lang, f", room {j['room']}", f", कमरा {j['room']}")) if j.get("room") else ""


def _has_photo(tid: str, jid: str, kind: str) -> bool:
    return mongo.col("photos").count_documents({"tenant_id": tid, "job_id": jid, "kind": kind}, limit=1) > 0


def parse_issue(text: str) -> dict | None:
    t = concierge.norm(text)
    m = re.search(r"(?:room|kamra|kamre|कमरा|कमरे|rm)\s*(?:no\.?|number|नंबर)?\s*(\d{3,4})", t) or re.search(r"(?<!\d)(\d{3,4})(?!\d)", t)
    if not m:
        return None
    room = m.group(1)
    issue = re.sub(r"\s+", " ", re.sub(r"(?:report|please|kripya)", "", text, flags=re.I)).strip(" .,:")[:140]
    hit = issues.top(issue)  # same guest-issue taxonomy as the concierge (pests, leaks, locks, safety, ...)
    urgency = hit["urgency"] if hit else ("high" if concierge.has(" " + t + " ", URGENT) else "medium")
    return {
        "room": room,
        "issue": issue,
        "department": hit["department"] if hit else dispatch.infer_department(issue),
        "urgency": urgency,
        "issue_type": hit["type"] if hit else None,
    }


def command(tid: str, emp: str, text: str, lang_hint: str = "en") -> dict:
    t = " " + concierge.norm(text) + " "
    lang = concierge.detect_lang(text, lang_hint)
    lang = "hi" if lang in ("hi", "hinglish") or lang_hint == "hi" else "en"
    offer, active = _jobs(tid, emp)
    cur = active[0] if active else None

    def out(intent: str, reply: str, action: str | None = None, params: dict | None = None, label: str = "") -> dict:
        prop = {"action": action, "params": params or {}, "label": label} if action else None
        return {"intent": intent, "reply": reply, "lang": lang, "proposed_action": prop}

    issue = parse_issue(text) if concierge.has(t, WORDS["issue"]) or issues.top(text) else None
    if issue:
        dept_label = issue["department"].replace("_", " ")
        return out(
            "report_issue",
            _t(
                lang,
                f"Report for room {issue['room']} to {dept_label}: {issue['issue']}. Confirm to send.",
                f"कमरा {issue['room']} की रिपोर्ट {dept_label} को: {issue['issue']}। भेजने के लिए Confirm दबाएँ।",
            ),
            "report_issue",
            issue,
            _t(lang, f"Report: room {issue['room']} · {dept_label}", f"रिपोर्ट: कमरा {issue['room']} · {dept_label}"),
        )
    if concierge.has(t, WORDS["done"]):
        if cur and cur["status"] == "in_progress":
            return out(
                "done",
                _t(
                    lang,
                    f"Great work. To finish '{_title(cur)}', take the after photo now.",
                    f"बढ़िया। '{_title(cur)}' पूरा करने के लिए अब बाद की फ़ोटो लें।",
                ),
                "photo",
                {"job_id": cur["id"], "kind": "after"},
                _t(lang, "Take AFTER photo", "बाद की फ़ोटो लें"),
            )
        return out("done", _t(lang, "You have no job in progress right now.", "अभी आपका कोई काम चालू नहीं है।"))
    if concierge.has(t, WORDS["start"]):
        if cur and cur["status"] == "accepted":
            if not _has_photo(tid, cur["id"], "before"):
                return out(
                    "start",
                    _t(lang, f"Take the before photo to start '{_title(cur)}'.", f"'{_title(cur)}' शुरू करने के लिए पहले की फ़ोटो लें।"),
                    "photo",
                    {"job_id": cur["id"], "kind": "before"},
                    _t(lang, "Take BEFORE photo", "पहले की फ़ोटो लें"),
                )
            return out(
                "start",
                _t(lang, f"Start '{_title(cur)}'?", f"'{_title(cur)}' शुरू करें?"),
                "start",
                {"job_id": cur["id"]},
                _t(lang, f"Start: {_title(cur)}", f"शुरू करें: {_title(cur)}"),
            )
        return out("start", _t(lang, "There is no accepted job to start.", "शुरू करने के लिए कोई स्वीकार किया हुआ काम नहीं है।"))
    if concierge.has(t, WORDS["decline"]) and offer:
        return out(
            "decline",
            _t(lang, f"Decline '{_title(offer)}'? It will go to a colleague.", f"'{_title(offer)}' मना करें? यह किसी साथी को जाएगा।"),
            "decline",
            {"job_id": offer["id"]},
            _t(lang, f"Decline: {_title(offer)}", f"मना करें: {_title(offer)}"),
        )
    if concierge.has(t, WORDS["accept"]):
        if offer:
            return out(
                "accept",
                _t(lang, f"Accept '{_title(offer)}'{_room_txt(offer, lang)}?", f"'{_title(offer)}'{_room_txt(offer, lang)} स्वीकार करें?"),
                "accept",
                {"job_id": offer["id"]},
                _t(lang, f"Accept: {_title(offer)}", f"स्वीकार: {_title(offer)}"),
            )
        return out("accept", _t(lang, "There is no new job offer right now.", "अभी कोई नया काम नहीं आया है।"))
    if concierge.has(t, WORDS["shift"]):
        me = dispatch.shifts_for(tid, emp)
        ctx = dispatch.get_context(tid)
        today = ctx.get("day")
        s = next((x for x in me["shifts"] if x["date"] == today), None)
        if s:
            return out(
                "my_shift",
                _t(lang, f"Today you have the {s['shift']} shift, {s['hours']} hours.", f"आज आपकी {s['shift']} शिफ़्ट है, {s['hours']} घंटे।"),
            )
        nxt = me["shifts"][0] if me["shifts"] else None
        if nxt:
            return out(
                "my_shift", _t(lang, f"Your next shift: {nxt['date']}, {nxt['shift']}.", f"आपकी अगली शिफ़्ट: {nxt['date']}, {nxt['shift']}।")
            )
        return out("my_shift", _t(lang, "No roster is published for you yet.", "आपका रोस्टर अभी नहीं डाला गया है।"))
    if concierge.has(t, WORDS["help"]):
        return out("help", _help(lang))
    if concierge.has(t, WORDS["next"]) or len(t.split()) <= 2:
        if offer:
            return out(
                "whats_next",
                _t(
                    lang,
                    f"New job: {_title(offer)}{_room_txt(offer, lang)}. {offer['seconds_left']} seconds to accept. Say accept or decline.",
                    f"नया काम: {_title(offer)}{_room_txt(offer, lang)}। स्वीकार करने के लिए {offer['seconds_left']} सेकंड। 'स्वीकार' या 'मना' बोलें।",
                ),
                "accept",
                {"job_id": offer["id"]},
                _t(lang, f"Accept: {_title(offer)}", f"स्वीकार: {_title(offer)}"),
            )
        if cur:
            nxt = _t(
                lang,
                "take the before photo to start" if cur["status"] == "accepted" else "take the after photo when done",
                "शुरू करने के लिए पहले की फ़ोटो लें" if cur["status"] == "accepted" else "काम पूरा होने पर बाद की फ़ोटो लें",
            )
            return out(
                "whats_next",
                _t(
                    lang,
                    f"Your job: {_title(cur)}{_room_txt(cur, lang)}. Next, {nxt}.",
                    f"आपका काम: {_title(cur)}{_room_txt(cur, lang)}। अब {nxt}।",
                ),
            )
        return out(
            "whats_next",
            _t(
                lang,
                "No jobs right now. Keep the app open; you will get a buzz.",
                "अभी कोई काम नहीं है। ऐप खुला रखें; काम आने पर फ़ोन वाइब्रेट होगा।",
            ),
        )
    return out("help", _t(lang, "Sorry, I didn't get that. ", "माफ़ कीजिए, समझ नहीं आया। ") + _help(lang))


def _help(lang: str) -> str:
    return _t(
        lang,
        "You can say: what's next, accept, decline, start, done, my shift, or report a problem like 'room 204 tap leaking'.",
        "आप बोल सकते हैं: अगला काम, स्वीकार, मना, शुरू, हो गया, मेरी शिफ़्ट, या समस्या जैसे 'कमरा 204 नल लीक'।",
    )


def act(tid: str, emp: str, actor: str, action: str, params: dict) -> dict:
    """Execute a confirmed voice action with the same rules as the buttons."""
    if action in ("accept", "decline", "start"):
        jid = str(params.get("job_id") or "")
        if not jid:
            raise Invalid("job_id is required.")
        fn = {"accept": dispatch.accept, "decline": dispatch.decline, "start": dispatch.start}[action]
        job = fn(tid, jid, emp)
        tenants.audit(tid, actor, f"voice.{action}", jid)
        return {"ok": True, "action": action, "job": {k: job.get(k) for k in ("id", "title", "status", "room")}}
    if action == "report_issue":
        room = str(params.get("room") or "").strip()[:8]
        issue = " ".join(str(params.get("issue") or "").split())[:140]
        if not room or not issue:
            raise Invalid("Say the room number and the problem.")
        r = mongo.col("rooms").find_one({"tenant_id": tid, "number": room}, {"id": 1})
        if not r:
            raise NotFound(f"Room {room} not found.")
        dept = params.get("department") if params.get("department") in tenants.DEPARTMENTS else dispatch.infer_department(issue)
        urgency = params.get("urgency") if params.get("urgency") in dispatch.URGENCY else "medium"
        hit = issues.top(issue)
        job = dispatch.create_job(
            tid,
            f"{issue} · room {room}",
            dept,
            room,
            urgency,
            "voice",
            actor,
            room_id=r["id"],
            kind="general",
            target_minutes=hit["target_minutes"] if hit else None,
        )
        tenants.audit(tid, actor, "voice.report_issue", f"{job['id']} room {room}")
        return {"ok": True, "action": action, "job": {k: job.get(k) for k in ("id", "title", "status", "department", "urgency", "room")}}
    raise Invalid("This action needs the app buttons.")
