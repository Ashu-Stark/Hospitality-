"""A minimal English / Hindi switch for the hotel portal: the Today page and the main navigation only.

The choice is kept in the session (st.session_state["lang"]); everything else stays in English. Unknown strings fall
back to English. The Hindi wording is a DRAFT for the hospitality-management student to check, like the onboarding
questions; keep it short and plain.
"""

from __future__ import annotations

import streamlit as st

LANGS = {"en": "English", "hi": "हिंदी"}

HI = {
    # navigation (sections, Today's pages, sign out)
    "Today": "आज",
    "People": "टीम",
    "Rooms & guests": "कमरे और मेहमान",
    "Stock": "स्टॉक",
    "Settings": "सेटिंग्स",
    "Sign out": "साइन आउट",
    "Overview": "सारांश",
    "Jobs": "काम",
    "Tasks": "टास्क",
    "Week numbers": "हफ़्ते के आंकड़े",
    "Voice note": "वॉइस नोट",
    # Today: header, answer and the five tiles
    "Today · Hotel mode": "आज · होटल मोड",
    "Good to see you · Homestay mode": "स्वागत है · होमस्टे मोड",
    "Looking at": "प्रॉपर्टी",
    "Checking today…": "आज की जाँच हो रही है…",
    "Yes, everything looks fine today.": "हाँ, आज सब ठीक लग रहा है।",
    "Mostly fine. Look at: ": "ज़्यादातर ठीक है। इन्हें देखें: ",
    "rooms to clean": "साफ़ करने वाले कमरे",
    "staff short": "स्टाफ़ की कमी",
    "guest requests": "मेहमानों के अनुरोध",
    "low supplies": "कम सामान",
    "Rooms with guests": "मेहमानों वाले कमरे",
    "Rooms to clean or check": "सफ़ाई या जाँच वाले कमरे",
    "Staff on shift": "शिफ़्ट पर स्टाफ़",
    "Team today": "आज की टीम",
    "Guest requests waiting": "इंतज़ार में मेहमानों के अनुरोध",
    "Supplies running low": "कम होता सामान",
    "Nobody has booked a checkout yet": "अभी किसी ने चेकआउट बुक नहीं किया",
    "From the room board": "रूम बोर्ड से",
    "Room board not available": "रूम बोर्ड उपलब्ध नहीं",
    "Your whole team": "आपकी पूरी टीम",
    "Enough people for this shift": "इस शिफ़्ट के लिए पूरे लोग",
    "Nobody on the shift plan right now": "अभी शिफ़्ट प्लान में कोई नहीं",
    "No guest is waiting": "कोई मेहमान इंतज़ार में नहीं",
    "Not available for your role": "आपकी भूमिका के लिए उपलब्ध नहीं",
    "Stock is fine": "स्टॉक ठीक है",
    "See rooms": "कमरे देखें",
    "Check rooms": "कमरे जाँचें",
    "Ask for extra staff": "अतिरिक्त स्टाफ़ माँगें",
    "See who": "कौन है, देखें",
    "Our team": "हमारी टीम",
    "See requests": "अनुरोध देखें",
    "Order stock": "सामान मँगाएँ",
    "See stock": "स्टॉक देखें",
    # Today: "also needs you"
    "Also needs you": "इन पर भी ध्यान दें",
    "Send again": "फिर भेजें",
    "See jobs": "काम देखें",
    "Decide": "फ़ैसला करें",
    "See team": "टीम देखें",
    "Details: where these numbers come from": "विवरण: ये आंकड़े कहाँ से आते हैं",
}


def lang() -> str:
    v = st.session_state.get("lang")
    return v if v in LANGS else "en"


def t(text: str) -> str:
    """Hindi when the session chose Hindi and a translation exists; otherwise the English text."""
    return HI.get(text, text) if lang() == "hi" else text


def toggle(key: str = "lang_toggle") -> None:
    """One small button that switches between English and Hindi (it shows the other language's name)."""
    other = "en" if lang() == "hi" else "hi"
    if st.button(LANGS[other], key=key, type="tertiary", help="Language for Today and the main menu"):
        st.session_state["lang"] = other
        st.rerun()
