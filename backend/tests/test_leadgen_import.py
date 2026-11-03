import json
import sqlite3

import pytest

from app.ingest import leadgen_import
from app.models import Business, DataSource


def _old_db(tmp_path):
    p = tmp_path / "leads.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE leads (lead_id TEXT, data TEXT, status TEXT)")
    good = {"business_name": "Swasthya Ayurveda", "country": "AE", "city": "Dubai", "industry": "clinics",
            "phone": "+97143977886", "website": "https://www.swasthyaayurveda.com/", "whatsapp": "+971558265074",
            "social_links": "https://instagram.com/swasthya; junk", "lead_score": 71, "date_collected": "2026-10-30",
            "decision_maker": "Dr. Divya Menon (Medical Director)", "source": "openstreetmap"}
    dropped = {**good, "business_name": "No Phone Shop", "phone": ""}
    no_name = {**good, "business_name": "  ", "phone": "+97142220000"}
    for d, st in ((good, "borderline"), (dropped, "drop"), (no_name, "keep")):
        con.execute("INSERT INTO leads VALUES (?,?,?)", ("x", json.dumps(d), st))
    con.commit()
    con.close()
    return p


def test_import_keeps_callable_leads_and_their_history(session, tmp_path):
    r = leadgen_import.run(session, _old_db(tmp_path))
    assert (r.read, r.new, r.skipped_dropped, r.skipped_invalid) == (3, 1, 1, 1)
    b = session.query(Business).one()
    assert b.source == "leadgen_import" and b.phone == "+97143977886"
    assert b.details["leadgen"]["whatsapp"] == "+971558265074" and b.details["leadgen"]["lead_score"] == 71
    assert len(b.social_profiles) == 1  # "junk" ignored
    assert {d.source_type for d in session.query(DataSource)} == {"leadgen_import"}


def test_import_twice_adds_nothing_new(session, tmp_path):
    db = _old_db(tmp_path)
    leadgen_import.run(session, db)
    again = leadgen_import.run(session, db)
    assert (again.new, again.updated) == (0, 1)


def test_missing_old_database_is_a_clear_error(session, tmp_path):
    with pytest.raises(FileNotFoundError):
        leadgen_import.run(session, tmp_path / "nope.db")
