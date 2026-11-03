from dataclasses import replace

from app.ingest.apify_maps import StandardRecord, to_record
from app.ingest.records import dedupe, problems, save
from app.models import Business, DataSource, SocialProfile, Verification
from tests.fakes import place


def rec(**kw) -> StandardRecord:
    return replace(to_record(place(), "AE", "Dubai", "beauty"), **kw)


def test_validation_rules():
    assert problems(rec()) == []
    assert "missing business name" in problems(rec(name=" "))
    assert "no valid phone and no website" in problems(rec(phone="", website_url=""))


def test_dedupe_by_phone_website_place_and_nearby_name():
    a = rec()
    b = rec(place_id="ChIJ2", website_url="", email="info@glowsalon.ae")  # same phone
    c = rec(place_id="ChIJ3", phone="+971509999999", website_url="https://www.glowsalon.ae/contact")  # same site
    d = rec(place_id="ChIJ4", phone="", website_url="https://other.ae", lat=25.1001)  # same name, ~11 m away
    e = rec(name="Different Spa", place_id="ChIJ5", phone="+971508888888", website_url="https://spa.ae",
            lat=25.3, lon=55.4)
    out = dedupe([a, b, c, d, e])
    assert len(out) == 2
    merged = next(r for r in out if r.name == "Glow Ladies Salon")
    assert merged.email == "info@glowsalon.ae"  # filled from the duplicate, original fields kept


def test_save_creates_business_with_provenance_and_candidate_socials(session):
    res = save(session, [rec(), rec(name="", place_id="X")])
    assert (res.new, res.updated) == (1, 0)
    assert res.rejected[0][1] == "missing business name"
    b = session.get(Business, res.business_ids[0])
    assert b.business_id == "BUS-0001" and b.details["last_review_date"] == "2026-10-25"
    fields = {d.field for d in session.query(DataSource).all()}
    assert {"name", "phone", "website_url", "rating"} <= fields
    assert all(d.verification_status == Verification.UNVERIFIED for d in b.data_sources)
    sp = session.query(SocialProfile).one()
    assert sp.platform == "instagram" and sp.verification_status == Verification.UNVERIFIED


def test_second_collection_fills_gaps_but_never_overwrites(session):
    save(session, [rec(email="")])
    res = save(session, [rec(email="info@glowsalon.ae", rating=1.0)])
    assert (res.new, res.updated) == (0, 1)
    b = session.query(Business).one()
    assert b.email == "info@glowsalon.ae" and b.rating == 4.6
    assert session.query(SocialProfile).count() == 1  # same profile not added twice
