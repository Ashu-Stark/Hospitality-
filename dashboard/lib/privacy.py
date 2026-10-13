"""Pay is private: reasons, talking points and next steps about pay or salary are shown only to the owner and HR.

Every other role that can open the check-in pages (department heads) sees "Private: ask HR" in their place. This is a
display rule on top of the API's own role checks; the attrition data itself is SYNTHETIC.
"""

from __future__ import annotations

import re
from dataclasses import replace

from . import auth

PRIVATE = "Private: ask HR"
PAY_ROLES = ("owner", "hr")
PAY_CATEGORIES = {"pay_gap"}  # the model's pay driver; any other reason whose words are about pay is caught by _PAY
_PAY = re.compile(r"\b(pay|pays|paid|salary|salaries|wage|wages|raise|raises|allowance|allowances|bonus|bonuses|ctc)\b", re.I)


def sees_pay(role: str | None = None) -> bool:
    return (role if role is not None else auth.role()) in PAY_ROLES


def about_pay(text: str | None) -> bool:
    return bool(text) and bool(_PAY.search(str(text)))


def text(s: str, role: str | None = None) -> str:
    """The text itself, or PRIVATE when it is about pay and this role may not see pay."""
    return PRIVATE if about_pay(s) and not sees_pay(role) else s


def is_pay_driver(d) -> bool:
    return d.category in PAY_CATEGORIES or about_pay(d.title)


def drivers(ds: list, role: str | None = None) -> list:
    """Copies of the drivers with pay reasons replaced by PRIVATE (titles kept unique, so a chart keeps one bar each)."""
    if sees_pay(role):
        return list(ds)
    out, n = [], 0
    for d in ds:
        if is_pay_driver(d):
            n += 1
            out.append(replace(d, title=PRIVATE if n == 1 else f"{PRIVATE} ({n})", reason=""))
        elif about_pay(d.reason):
            out.append(replace(d, reason=PRIVATE))
        else:
            out.append(d)
    return out


# ------------------------------------------------------------------ department heads see their own team only
WHOLE_HOTEL_ROLES = ("owner", "hr", "platform_admin")


def my_department() -> str | None:
    """The signed-in department head's department, from the hotel's staff list (their own employee id). None if unknown."""
    from . import platform

    u = auth.current() or {}
    emp = u.get("employee_id")
    if not emp:
        return None
    try:
        rows = platform.staff()
    except platform.PlatformError:
        return None
    return next((s.get("department") for s in rows if s.get("employee_id") == emp), None)


def team_scope(scores: list, depts: dict[str, str]) -> tuple[list, str | None]:
    """(the scores this role may see, the department they are limited to or None for the whole hotel)."""
    if auth.role() in WHOLE_HOTEL_ROLES:
        return scores, None
    dept = my_department()
    if not dept:
        return [], None
    return [s for s in scores if depts.get(s.employee_id) == dept], dept
