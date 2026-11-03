"""Auto-send: every few minutes, new leads go to Harvey on their own (when switched on).

Every lead with a website or an email goes, audited ones first. A lead sent before its audit goes once more
after it, so Harvey gets the proposal email's facts. Same path as the Outreach page's "Send": `harvey import`,
then the lead is marked as sent. Harvey keeps its own checks (dedupe, do-not-contact, email verification)
and its own send limits (channels.email.max_hourly_sends / max_daily_sends; approval if switched on).
Off by default; an admin switches it on (Outreach page or PUT /api/harvey/auto).
"""
from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from ..harvey import bridge
from ..models import AppSetting

KEY = "harvey_auto"
CHECK_EVERY_S = 10 * 60
FIRST_CHECK_S = 60   # let the server settle after a restart
log = logging.getLogger(__name__)


def get_setting(session: Session) -> dict:
    row = session.get(AppSetting, KEY)
    return {"enabled": False, "last_run": None, "last_result": None, **((row.value or {}) if row else {})}


def set_setting(session: Session, enabled: bool, by: str) -> dict:
    row = session.get(AppSetting, KEY) or AppSetting(key=KEY)
    row.value, row.updated_by = {**get_setting(session), "enabled": enabled}, by
    session.add(row)
    session.commit()
    return get_setting(session)


def _record(session: Session, result: str) -> None:
    row = session.get(AppSetting, KEY)
    if row is not None:
        row.value = {**(row.value or {}), "last_run": datetime.now(UTC).isoformat(timespec="seconds"),
                     "last_result": result}
        session.commit()


def run_once(session: Session) -> str:
    """Send up to one batch of leads Harvey has not had in their latest form. Returns a one-line result (also saved on the setting)."""
    from ..harvey_routes import auto_candidates, send_batch  # routes import services; avoid a cycle
    if not get_setting(session)["enabled"]:
        return "off"
    if not bridge.config().ready:
        result = "Harvey is not set up"
    else:
        leads = auto_candidates(session, bridge.MAX_BATCH)
        if not leads:
            return "nothing new"  # not saved: keeps the last real send visible
        try:
            r = send_batch(session, leads, "auto")
            result = f"sent {len(leads)} leads ({r.get('new', '?')} new in Harvey)"
        except bridge.HarveyUnavailable as e:
            session.rollback()
            result = f"failed: {e}"
    _record(session, result)
    return result


class HarveyAutoSend:
    def __init__(self, make_session: sessionmaker):
        self.make_session = make_session
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="harvey-auto", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        if self._stop.wait(FIRST_CHECK_S):
            return
        while not self._stop.is_set():
            try:
                with self.make_session() as session:
                    result = run_once(session)
                if result not in ("off", "nothing new"):
                    log.info("harvey auto-send: %s", result)
            except Exception:  # keep the thread alive; the next round tries again
                log.exception("harvey auto-send round failed")
            self._stop.wait(CHECK_EVERY_S)
