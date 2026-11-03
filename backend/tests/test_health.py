def test_health_reports_ok_and_never_shows_tokens(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert isinstance(body["apify_tokens"], int)  # a count only, never the token itself
