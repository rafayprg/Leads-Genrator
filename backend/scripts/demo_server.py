"""Demo backend for trying the dashboard without spending Apify credit.

Uses data/demo.db (never the real data/audit.db) and a fake Apify that returns made-up places.
Demo login (demo database only): demo@techdeva.local / Demo-pass-2026
Run from the backend folder:  .venv\\Scripts\\python scripts\\demo_server.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))
os.environ["DATABASE_URL"] = f"sqlite:///{(BACKEND / 'data' / 'demo.db').as_posix()}"
os.environ["APIFY_API_TOKENS"] = "demo_token_not_real_0000"

import uvicorn  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Base, make_engine  # noqa: E402
from app.ingest import apify_maps, apify_tokens  # noqa: E402
from app.main import create_app  # noqa: E402

DEMO_EMAIL, DEMO_PASSWORD = "demo@techdeva.local", "Demo-pass-2026"
DEMO_PLACES = [
    ("Glow Ladies Salon", "beauty", "Beauty salon", "Al Barsha", "+971501234567", "https://glow-demo.example", 4.6, 120),
    ("Bright Smile Dental", "clinics", "Dental clinic", "Jumeirah", "+97143334444", "https://smile-demo.example", 4.8, 310),
    ("Skill Up Training Centre", "academies", "Training centre", "Deira", "+97142225555", "", 4.2, 45),
    ("Lotus Spa & Wellness", "beauty", "Spa", "Business Bay", "+971552223333", "https://lotus-demo.example", 4.4, 88),
    ("Al Noor Physio Clinic", "clinics", "Physiotherapy clinic", "Karama", "+97143338888", "https://alnoor-demo.example", 3.9, 26),
]


def fake_collect(targets, industries, budget_usd, per_search=40, log=print, on_batch=None, **_):
    log("DEMO: fake Apify run, nothing is spent")
    recs = []
    for cc, city in targets:
        for i, (name, ind, cat, area, phone, web, rating, reviews) in enumerate(DEMO_PLACES):
            if ind not in industries:
                continue
            item = {"title": f"{name} ({city})" if city != "Dubai" else name, "city": city, "neighborhood": area,
                    "phoneUnformatted": phone if city == "Dubai" else "",
                    "website": web.replace("-demo", f"-{city.lower().replace(' ', '')}-demo") if web else "",
                    "categoryName": cat,
                    "totalScore": rating, "reviewsCount": reviews, "placeId": f"demo-{cc}-{city}-{i}",
                    "url": f"https://maps.google.com/?cid=demo{i}",
                    "reviews": [{"publishedAtDate": "2026-10-20T09:00:00.000Z"}],
                    "instagram": f"https://www.instagram.com/demo_{i}" if i % 2 == 0 else ""}
            r = apify_maps.to_record(item, cc, city, ind)
            if r:
                recs.append(r)
    info = {"run_id": "demo", "account": "demo account", "status": "SUCCEEDED", "items": len(recs),
            "cost_usd": round(len(recs) * 0.0045, 4)}
    if on_batch and recs:
        on_batch(recs, info)
    return apify_maps.CollectResult(tuple(recs), round(len(recs) * 0.0045, 4), "", (info,))


def fake_status(token, fresh=False):
    return apify_tokens.TokenStatus(key=apify_tokens.mask(token), last4=token[-4:], ok=True, message="OK (demo)",
                                    username="demo-account", plan="FREE", limit_usd=5.0, used_usd=0.42,
                                    remaining_usd=4.58, cycle_ends="2026-11-30")


if __name__ == "__main__":
    engine = make_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    from app.models import Role, User
    from app.security import hash_password
    with sessionmaker(bind=engine)() as s:
        if not s.query(User).count():  # demo-only admin; the real database starts empty and asks for setup
            s.add(User(email=DEMO_EMAIL, name="Demo admin", password_hash=hash_password(DEMO_PASSWORD), role=Role.ADMIN))
            s.commit()
    apify_tokens.status = fake_status  # demo only: no network calls to Apify
    app = create_app(make_session=sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
                     collect=fake_collect)
    from app import db as app_db
    app_db.SessionLocal.configure(bind=engine)  # requests use the demo database too
    uvicorn.run(app, host="127.0.0.1", port=8800)
