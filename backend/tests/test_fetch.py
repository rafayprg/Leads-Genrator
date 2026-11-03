import pytest

from app.agents.website.fetch import HostNotFound, SafeFetcher, UnsafeURL, _ip_is_public
from tests.sitekit import Site


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/", "http://user:pw@example.com/", "http://example.com:22/",
    "http://127.0.0.1/", "http://localhost/", "http://10.0.0.5/", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://0.0.0.0/",
])
def test_unsafe_urls_are_refused(url):
    with pytest.raises(UnsafeURL):
        SafeFetcher().check_url(url)


def test_public_and_mapped_addresses():
    assert _ip_is_public("8.8.8.8")
    assert not _ip_is_public("::ffff:127.0.0.1") and not _ip_is_public("100.64.0.1")


@pytest.fixture()
def site():
    s = Site({
        "/": "<html><body><a href='/a'>a</a></body></html>",
        "/a": (301, "", {"Location": "/b"}),
        "/b": "<p>final</p>",
        "/loop": (302, "", {"Location": "/loop"}),
        "/big": "x" * 5000,
        "/private": "secret",
        "/robots.txt": (200, "User-agent: *\nDisallow: /private\n", {"Content-Type": "text/plain"}),
        "/to-metadata": (302, "", {"Location": "http://169.254.169.254/latest/"}),
    })
    yield s
    s.close()


def test_follows_redirects_and_records_the_chain(site):
    r = SafeFetcher(allow_private=True, delay=0).get(site.url + "/a")
    assert r.ok and r.final_url.endswith("/b") and r.redirects[0][1] == 301 and "final" in r.text


def test_redirect_loop_stops(site):
    r = SafeFetcher(allow_private=True, delay=0).get(site.url + "/loop")
    assert not r.ok and "redirects" in r.error


def test_robots_txt_is_respected(site):
    r = SafeFetcher(allow_private=True, delay=0).get(site.url + "/private")
    assert r.blocked == "robots" and r.text == ""


def test_size_cap(site):
    r = SafeFetcher(allow_private=True, delay=0, max_bytes=1000).get(site.url + "/big")
    assert r.truncated and r.bytes_read < 5000


def test_redirect_to_a_private_address_is_blocked(site, monkeypatch):
    f = SafeFetcher(allow_private=True, delay=0)
    real = f.check_url

    def strict_for_metadata(url):
        if "169.254" in url:
            return SafeFetcher().check_url(url)  # the real, strict check
        return real(url)

    monkeypatch.setattr(f, "check_url", strict_for_metadata)
    r = f.get(site.url + "/to-metadata")
    assert r.blocked == "unsafe" and "non-public" in r.error


def test_unknown_domain_is_not_called_unsafe():
    with pytest.raises(HostNotFound):
        SafeFetcher().check_url("https://no-such-domain-techdeva-test.invalid/")
    r = SafeFetcher().get("https://no-such-domain-techdeva-test.invalid/")
    assert r.blocked == "" and "domain name not found" in r.error


def test_temporary_dns_failure_is_not_blamed_on_the_business(monkeypatch):
    import socket

    from app.agents.website import agent, fetch

    def flaky(*a, **k):
        raise socket.gaierror(11002, "getaddrinfo failed")

    monkeypatch.setattr(fetch.socket, "getaddrinfo", flaky)
    monkeypatch.setattr(fetch, "DNS_RETRY_WAITS", (0, 0, 0))
    r = SafeFetcher().get("https://some-real-business.ae/")
    assert r.error.startswith("DNS lookup failed") and r.blocked == ""
    res = agent.audit("https://some-real-business.ae/", "beauty", use_browser=False)
    assert res.status == "failed" and res.findings == [] and "Nothing was concluded" in res.limitations[0]
