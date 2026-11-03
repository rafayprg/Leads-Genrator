"""Talk to the Harvey that runs on the VPS — only over SSH.

- Harvey's dashboard listens on the VPS's 127.0.0.1:5555 only; we call it there with `curl`, and the
  dashboard token is read on the VPS (`data/dashboard-token`), so it never reaches this computer.
- Leads go in through Harvey's own `harvey import` (the CSV is piped over SSH into a temp file that is
  deleted afterwards). Harvey keeps its own checks: dedupe, do-not-contact, email verification,
  and every email still waits for approval in Harvey's Outbox.
- Every remote command is built from fixed text plus shell-quoted settings; nothing typed by a user
  or scraped from a website is ever put into a command (lead data only travels as CSV on stdin).
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

SSH_TIMEOUT_S = 25
IMPORT_TIMEOUT_S = 180
STATUS_CACHE_S = 20
MAX_BATCH = 50
READ_PATHS = ("/api/harvey/status", "/api/sending-mode", "/api/stats", "/api/outbox")
CSV_COLUMNS = ("name", "website", "city", "category", "phone", "instagram", "facebook", "owner", "owner_title", "email",
               "finding_1", "finding_2", "techdeva_line")  # the last three: proposal email facts from the audit
_cache: dict = {}
_lock = threading.Lock()


class HarveyUnavailable(Exception):
    """Harvey could not be reached or answered with an error; the text is safe to show."""


@dataclass(frozen=True)
class HarveyConfig:
    host: str
    user: str
    key: str
    folder: str
    public_url: str

    @property
    def ready(self) -> bool:
        return bool(self.host) and Path(self.key).is_file()


def config() -> HarveyConfig:
    return HarveyConfig(
        host=os.getenv("HARVEY_SSH_HOST", "").strip(),
        user=os.getenv("HARVEY_SSH_USER", "root").strip() or "root",
        key=os.path.expanduser(os.getenv("HARVEY_SSH_KEY", "~/.ssh/techdeva_vps").strip()),
        folder=os.getenv("HARVEY_DIR", "/opt/harvey").strip() or "/opt/harvey",
        public_url=os.getenv("HARVEY_PUBLIC_URL", "https://sales.techdeva.net").strip(),
    )


def _ssh(cfg: HarveyConfig, remote: str, data: bytes | None = None, timeout: int = SSH_TIMEOUT_S) -> str:
    if not cfg.ready:
        raise HarveyUnavailable("Harvey is not set up (Settings → Harvey: VPS address and SSH key)")
    cmd = ["ssh", "-i", cfg.key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
           "-o", "StrictHostKeyChecking=accept-new", f"{cfg.user}@{cfg.host}", remote]
    try:
        r = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as e:
        raise HarveyUnavailable(f"The VPS did not answer within {timeout} s") from e
    except OSError as e:
        raise HarveyUnavailable(f"Could not start ssh: {e}") from e
    out = r.stdout.decode("utf-8", "replace")
    if r.returncode != 0:
        err = (r.stderr.decode("utf-8", "replace") or out).strip().splitlines()
        raise HarveyUnavailable(f"VPS command failed (exit {r.returncode}): {err[-1][:200] if err else 'no output'}")
    return out


def _read_all(cfg: HarveyConfig) -> dict:
    """One SSH round trip: every read endpoint, as {path: parsed JSON or {'error': ...}}."""
    folder = shlex.quote(cfg.folder)
    parts = []
    for p in READ_PATHS:
        parts.append(f"echo '@@{p}'; curl -s --max-time 15 -H \"Authorization: Bearer $(cat data/dashboard-token)\" "
                     f"http://127.0.0.1:5555{p}; echo")
    out = _ssh(cfg, f"cd {folder} && " + "; ".join(parts))
    found: dict = {}
    for block in out.split("@@")[1:]:
        path, _, body = block.partition("\n")
        try:
            found[path.strip()] = json.loads(body.strip() or "{}")
        except ValueError:
            found[path.strip()] = {"error": "Harvey's dashboard did not answer (is harvey-dashboard running?)"}
    return found


def _pending_item(o: dict) -> dict:
    """Only what the list needs — never the email body."""
    ctx = o.get("context") if isinstance(o.get("context"), dict) else {}
    return {"id": o.get("id"), "subject": o.get("subject") or "", "to": o.get("to_email") or "",
            "company": ctx.get("company") or "", "contact": ctx.get("contact") or "",
            "email_status": ctx.get("email_status") or "", "kind": o.get("kind") or "", "created_at": o.get("created_at") or ""}


def status(fresh: bool = False) -> dict:
    cfg = config()
    base = {"configured": cfg.ready, "host": cfg.host, "public_url": cfg.public_url}
    if not cfg.ready:
        return {**base, "reachable": False, "error": "Not set up yet"}
    with _lock:
        hit = _cache.get("status")
        if hit and not fresh and time.time() - hit[0] < STATUS_CACHE_S:
            return hit[1]
    try:
        raw = _read_all(cfg)
    except HarveyUnavailable as e:
        return {**base, "reachable": False, "error": str(e)}
    stats, outbox = raw.get("/api/stats") or {}, raw.get("/api/outbox") or {}
    mode = raw.get("/api/sending-mode") or {}
    errors = [v["error"] for v in raw.values() if isinstance(v, dict) and v.get("error")]
    out = {**base, "reachable": not errors, "error": errors[0] if errors else None,
           "running": bool((raw.get("/api/harvey/status") or {}).get("running")),
           "mode": mode.get("mode"), "paused": bool(outbox.get("paused")),
           "pipeline": stats.get("pipeline") or {}, "prospects": (stats.get("prospects") or {}).get("total", 0),
           "outbox": {k: len(outbox.get(k) or []) for k in ("pending", "approved", "sent", "failed")},
           "pending_preview": [_pending_item(o) for o in (outbox.get("pending") or [])[:8]],
           "fetched_at": time.time()}
    with _lock:
        _cache["status"] = (time.time(), out)
    return out


def to_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: " ".join(str(r.get(k) or "").split()) for k in CSV_COLUMNS})  # no newlines inside a cell
    return buf.getvalue().encode("utf-8")


_IMPORTED = re.compile(r"IMPORT\s+\S+\s+(\d+)\s+new businesses,\s+(\d+)\s+already known")
_SUMMARY = re.compile(r"(\d+)\s+businesses,\s+(\d+)\s+with a website,\s+(\d+)\s+with an owner and email")


def import_rows(rows: list[dict], check_only: bool) -> dict:
    """Run `harvey import` on the VPS. check_only = Harvey reads the file and reports, saves nothing."""
    if not rows:
        raise HarveyUnavailable("No leads to send")
    if len(rows) > MAX_BATCH:
        raise HarveyUnavailable(f"At most {MAX_BATCH} leads per batch")
    cfg = config()
    folder = shlex.quote(cfg.folder)
    flags = f"--limit {len(rows)} --no-profile" + (" --check" if check_only else "")
    remote = (f"f=$(mktemp /tmp/techdeva-audit-XXXXXX.csv) && cat > \"$f\" && cd {folder} && "
              f".venv/bin/harvey import \"$f\" {flags}; rc=$?; rm -f \"$f\"; exit $rc")
    out = _ssh(cfg, remote, data=to_csv(rows), timeout=IMPORT_TIMEOUT_S)
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    report = {"check_only": check_only, "output": lines[-15:]}
    if m := _SUMMARY.search(out):
        report.update(rows=int(m[1]), with_website=int(m[2]), with_owner_email=int(m[3]))
    if m := _IMPORTED.search(out):
        report.update(new=int(m[1]), already_known=int(m[2]))
    with _lock:
        _cache.pop("status", None)
    return report
