"""A fake Apify API, so tests never spend credit or need a token."""
from __future__ import annotations


class FakeResponse:
    def __init__(self, code: int, data):
        self.status_code = code
        self._data = data
        self.content = b"x"
        self.text = str(data)

    def json(self):
        return self._data


def place(**kw) -> dict:
    item = {"title": "Glow Ladies Salon", "city": "Dubai", "neighborhood": "Al Barsha",
            "phoneUnformatted": "+971501234567", "website": "https://glowsalon.ae",
            "url": "https://maps.google.com/?cid=1", "totalScore": 4.6, "reviewsCount": 120,
            "categoryName": "Beauty salon", "placeId": "ChIJ1", "location": {"lat": 25.10, "lng": 55.20},
            "reviews": [{"publishedAtDate": "2026-10-25T10:00:00.000Z"}],
            "instagram": "https://www.instagram.com/glowsalon",
            "openingHours": [{"day": "Monday", "hours": "10 AM to 9 PM"}]}
    item.update(kw)
    return item


class FakeApify:
    """accounts maps token -> remaining USD. Tokens in `refuse` answer 402 when a run starts."""

    def __init__(self, accounts: dict[str, float], items: list[dict], refuse: tuple[str, ...] = (),
                 final_status: str = "SUCCEEDED"):
        self.accounts, self.items, self.refuse, self.final_status = accounts, items, refuse, final_status
        self.started: list[str] = []

    def tokens(self):
        return tuple(self.accounts)

    def get(self, token, path, timeout=20):
        if path == "/users/me/limits":
            if token not in self.accounts:
                return FakeResponse(401, {})
            return FakeResponse(200, {"data": {"limits": {"maxMonthlyUsageUsd": 5},
                                                "current": {"monthlyUsageUsd": 5 - self.accounts[token]},
                                                "monthlyUsageCycle": {"endAt": "2026-11-30T00:00:00Z"}}})
        if path == "/users/me":
            return FakeResponse(200, {"data": {"username": "acct" + token[-4:], "plan": {"id": "FREE"}}})
        if path.startswith("/actor-runs/"):
            n = len(self.items)
            return FakeResponse(200, {"data": {"id": "run1", "status": self.final_status, "defaultDatasetId": "ds1",
                                               "chargedEventCounts": {"place-scraped": n, "review-scraped": n}}})
        if path.startswith("/datasets/"):
            return FakeResponse(200, self.items)
        return FakeResponse(404, {})

    def post(self, token, path, **kw):
        if path.endswith("/runs"):
            self.started.append(token)
            if token in self.refuse:
                return FakeResponse(402, {"error": {"type": "not-enough-usage-to-run-paid-actor"}})
            return FakeResponse(201, {"data": {"id": "run1", "status": "RUNNING", "defaultDatasetId": "ds1"}})
        return FakeResponse(200, {})
