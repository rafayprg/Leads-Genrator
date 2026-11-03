import pytest

from app.ingest import apify_maps as am
from app.ingest import apify_tokens as tk
from tests.fakes import FakeApify, place

A, B = "apify_api_" + "A" * 20 + "1111", "apify_api_" + "B" * 20 + "2222"


@pytest.fixture()
def fake(monkeypatch):
    def install(**kw):
        f = FakeApify(**kw)
        monkeypatch.setattr(tk, "tokens", f.tokens)
        monkeypatch.setattr(tk, "apify_get", f.get)
        monkeypatch.setattr(tk, "apify_post", f.post)
        monkeypatch.setattr(am, "POLL_SECONDS", 0)
        tk._cache.clear()
        return f
    return install


def quiet(_msg: str) -> None:
    pass


def test_switches_to_next_account_when_one_has_no_credit(fake):
    f = fake(accounts={A: 4.9, B: 3.0}, items=[place()], refuse=(A,))
    res = am.collect([("AE", "Dubai")], ["beauty"], budget_usd=2.0, per_search=10, log=quiet)
    assert f.started == [A, B]  # richest account first, then the next one
    assert res.problem == ""
    assert len(res.records) == 1 and res.runs[0]["account"] == "acct2222"
    assert res.spent_usd == pytest.approx(0.0045)


def test_no_token_is_a_clear_problem_not_a_silent_fallback(fake):
    fake(accounts={}, items=[])
    res = am.collect([("AE", "Dubai")], ["beauty"], budget_usd=2.0, log=quiet)
    assert res.records == () and "No Apify credit" in res.problem


def test_budget_below_actor_minimum_is_refused(fake):
    fake(accounts={A: 4.0}, items=[place()])
    res = am.collect([("AE", "Dubai")], ["beauty"], budget_usd=0.2, log=quiet)
    assert "at least" in res.problem and res.records == ()


def test_failed_run_with_no_items_switches_account(fake):
    f = fake(accounts={A: 4.9, B: 3.0}, items=[], final_status="FAILED")
    res = am.collect([("AE", "Dubai")], ["beauty"], budget_usd=2.0, log=quiet)
    assert f.started == [A, B] and "No Apify credit" in res.problem


def test_only_places_with_50_to_1000_reviews_are_kept(fake):
    counts = [None, 0, 49, 50, 300, 1000, 1001, 5000]
    fake(accounts={A: 4.9}, items=[place(title=f"P{n}", placeId=f"id{n}", reviewsCount=n) for n in counts])
    res = am.collect([("AE", "Dubai")], ["beauty"], budget_usd=2.0, log=quiet)
    assert sorted(r.review_count for r in res.records) == [50, 300, 1000]


def test_review_range_can_be_chosen_per_search(fake):
    fake(accounts={A: 4.9}, items=[place(title=f"P{n}", placeId=f"id{n}", reviewsCount=n) for n in (5, 20, 60, 2000)])
    res = am.collect([("AE", "Dubai")], ["beauty"], budget_usd=2.0, log=quiet, min_reviews=10, max_reviews=100)
    assert sorted(r.review_count for r in res.records) == [20, 60]


def test_cities_run_in_parallel_and_each_result_arrives_as_it_finishes(fake, monkeypatch):
    import threading
    import time
    live, peak, lock = [0], [0], threading.Lock()
    real = am.run_actor

    def slow_run(pool, run_input, cap, log):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.2)
        try:
            return real(pool, run_input, cap, log)
        finally:
            with lock:
                live[0] -= 1

    monkeypatch.setattr(am, "run_actor", slow_run)
    fake(accounts={A: 4.9, B: 4.9}, items=[place()])
    batches = []
    cities = [("AE", c) for c in ("Dubai", "Sharjah", "Ajman", "Al Ain")]
    t0 = time.time()
    res = am.collect(cities, ["beauty"], budget_usd=10.0, log=quiet, parallel=4,
                     on_batch=lambda recs, info: batches.append(info["city"]))
    assert peak[0] == 4 and time.time() - t0 < 0.7  # four 0.2 s runs together, not one after another
    assert sorted(batches) == sorted(c for _, c in cities) and len(res.runs) == 4


def test_parallel_runs_never_reserve_more_than_the_budget(fake):
    fake(accounts={A: 4.9}, items=[place()])
    res = am.collect([("AE", c) for c in ("Dubai", "Sharjah", "Ajman", "Al Ain")], ["beauty"], budget_usd=1.0,
                     per_search=10, log=quiet, parallel=4)
    assert res.problem == "" and res.spent_usd <= 1.0


def test_digital_marketing_agencies_are_searchable():
    assert "digital marketing agency" in am.INDUSTRIES["digital_marketing"]["search_terms"]


def test_record_takes_city_from_the_item_not_the_search():
    r = am.to_record(place(city="Riyadh", phoneUnformatted="+966112345678"), "SA", "Jeddah", "clinics")
    assert r.city == "Riyadh" and r.phone == "+966112345678" and r.phone_type == "landline"
    assert r.last_review_date == "2026-10-25"
    assert r.social_links == ("https://www.instagram.com/glowsalon",)
    assert r.opening_hours == ("Monday: 10 AM to 9 PM",)


def test_closed_or_nameless_places_are_skipped():
    assert am.to_record(place(permanentlyClosed=True), "AE", "Dubai", "beauty") is None
    assert am.to_record(place(title="  "), "AE", "Dubai", "beauty") is None


def test_token_status_reads_real_credit_and_masks(fake):
    fake(accounts={A: 1.25}, items=[])
    st = tk.status(A, fresh=True)
    assert st.ok and st.remaining_usd == 1.25 and st.key == "…1111"
    assert A not in str(st.as_dict())
    assert tk.status("apify_api_wrongwrongwrongwrong9999", fresh=True).message == "Invalid token"


def test_estimate():
    assert am.estimate_usd(1, ["beauty"], 40) == pytest.approx(6 * 40 * 0.0045, abs=0.01)
