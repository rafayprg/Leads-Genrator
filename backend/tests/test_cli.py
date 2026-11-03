from app import cli
from app.models import Role, User, UserSession
from app.security import check_password, hash_password


def test_reset_password_sets_new_hash_and_logs_out(session, monkeypatch, maker):
    monkeypatch.setattr(cli, "SessionLocal", maker)
    u = User(email="Boss@Example.com", name="Boss", role=Role.ADMIN, password_hash=hash_password("old-pass-123"))
    session.add(u)
    session.commit()
    session.add(UserSession(token_hash="x" * 64, user_id=u.id, ip="1.1.1.1", expires_at=u.created_at))
    session.commit()
    answers = iter(["new-pass-456", "new-pass-456"])
    msg = cli.reset_password("boss@example.com", ask=lambda _: next(answers))
    session.expire_all()
    assert "Password changed" in msg and check_password("new-pass-456", session.get(User, u.id).password_hash)
    assert session.query(UserSession).count() == 0


def test_reset_password_refuses_mismatch_weak_and_unknown(session, monkeypatch, maker):
    monkeypatch.setattr(cli, "SessionLocal", maker)
    session.add(User(email="a@b.com", name="A", role=Role.ADMIN, password_hash=hash_password("old-pass-123")))
    session.commit()
    pairs = iter(["new-pass-456", "other-pass-789", "short", "short"])
    assert "do not match" in cli.reset_password("a@b.com", ask=lambda _: next(pairs))
    assert "at least" in cli.reset_password("a@b.com", ask=lambda _: next(pairs))
    assert "No account" in cli.reset_password("x@y.com", ask=lambda _: "")
