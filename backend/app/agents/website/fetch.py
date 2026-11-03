"""Phase 2.1 — safe fetcher for business websites.

Business URLs come from the internet, so every request is checked before it is sent:
- only http/https, only ports 80/443, no user:password@ in the URL;
- the host must resolve ONLY to public IP addresses (no localhost, LAN, cloud metadata, ...);
- redirects are followed by hand and every hop is checked again (max 5);
- after connecting, the real peer address is checked again (defeats DNS re-binding for reading data);
- timeouts, a size cap per response, robots.txt respected, polite delay per site.
Residual risk (documented): a re-bound host could still receive one GET; nothing is read back from it.
"""
from __future__ import annotations

import ipaddress
import socket
import threading
import time
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests

USER_AGENT = "TechDevaAuditBot/0.2 (+https://techdeva.net; website audit for business owners)"
ALLOWED_PORTS = {80, 443}
MAX_REDIRECTS = 5
MAX_BYTES = 3_000_000
TIMEOUT = (8, 15)  # connect, read seconds
PER_HOST_DELAY = 1.0
DNS_RETRY_WAITS = (1.0, 2.0, 0.0)  # pause after attempt 1 and 2; no pause after the last
NAME_DOES_NOT_EXIST = {getattr(socket, "EAI_NONAME", -2), 11001}  # 11001 = WSAHOST_NOT_FOUND on Windows


class UnsafeURL(ValueError):
    """The URL points somewhere this tool must not go."""


class HostNotFound(OSError):
    """The DNS answer says this domain does not exist (typo or expired domain)."""


class DNSLookupFailed(HostNotFound):
    """The lookup itself failed on this computer; says nothing about the business."""


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str = ""
    status: int = 0
    headers: dict = field(default_factory=dict)
    text: str = ""
    redirects: tuple[tuple[str, int], ...] = ()
    elapsed_ms: int = 0
    bytes_read: int = 0
    truncated: bool = False
    error: str = ""
    tls_error: bool = False
    blocked: str = ""  # "robots" or "unsafe" when we refused to fetch

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 400 and not self.error and not self.blocked


def _resolve(host: str, port: int) -> list:
    """DNS lookup with retries: lookups on this laptop fail now and then for a second or two."""
    last: socket.gaierror | None = None
    for wait in DNS_RETRY_WAITS:
        try:
            return socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as e:
            last = e
            if e.errno in NAME_DOES_NOT_EXIST:
                break  # a definite "no such domain" answer: retrying will not help
            time.sleep(wait)
    if last is not None and last.errno in NAME_DOES_NOT_EXIST:
        raise HostNotFound(f"domain name not found ({last.strerror})") from last
    raise DNSLookupFailed("DNS lookup failed on this computer (temporary; retry later or check the computer's DNS "
                          "settings)") from last


def _ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


class SafeFetcher:
    def __init__(self, allow_private: bool = False, delay: float = PER_HOST_DELAY,
                 respect_robots: bool = True, max_bytes: int = MAX_BYTES):
        # allow_private exists ONLY for tests that serve pages from 127.0.0.1
        self.allow_private, self.delay, self.respect_robots, self.max_bytes = allow_private, delay, respect_robots, max_bytes
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en,ar;q=0.8"})
        self._session.trust_env = False  # never route through proxies from the environment
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- checks
    def check_url(self, url: str) -> str:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            raise UnsafeURL(f"scheme {p.scheme or '?'} not allowed")
        if not p.hostname:
            raise UnsafeURL("no host")
        if p.username or p.password:
            raise UnsafeURL("credentials in URL")
        port = p.port or (443 if p.scheme == "https" else 80)
        if self.allow_private:  # tests only: local site on a random port
            return url
        if port not in ALLOWED_PORTS:
            raise UnsafeURL(f"port {port} not allowed")
        infos = _resolve(p.hostname, port)
        ips = {i[4][0] for i in infos}
        bad = [ip for ip in ips if not _ip_is_public(ip)]
        if bad or not ips:
            raise UnsafeURL(f"host resolves to a non-public address ({', '.join(sorted(bad)) or 'none'})")
        return url

    def _peer_ok(self, resp: requests.Response) -> bool:
        if self.allow_private:
            return True
        try:
            sock = resp.raw.connection.sock  # urllib3 2.x
            return _ip_is_public(sock.getpeername()[0])
        except (AttributeError, OSError, ValueError):
            return True  # connection already pooled/closed; the pre-check above still applied

    def _wait(self, host: str) -> None:
        with self._lock:
            now = time.time()
            nxt = max(now, self._last.get(host, 0) + self.delay)
            self._last[host] = nxt
        if nxt > now:
            time.sleep(nxt - now)

    # ---------------------------------------------------------------- robots
    def robots(self, base: str) -> urllib.robotparser.RobotFileParser:
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            r = self.get(base + "/robots.txt", check_robots=False)
            if r.status in (401, 403):
                rp.disallow_all = True
            elif not r.ok:
                rp.allow_all = True
            else:
                rp.parse(r.text.splitlines())
            self._robots[base] = rp
        return self._robots[base]

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        return self.robots(f"{p.scheme}://{p.netloc}").can_fetch(USER_AGENT, url)

    # ---------------------------------------------------------------- fetch
    def get(self, url: str, check_robots: bool = True, method: str = "GET") -> FetchResult:
        chain: list[tuple[str, int]] = []
        current = url
        t0 = time.perf_counter()
        for _ in range(MAX_REDIRECTS + 1):
            try:
                self.check_url(current)
            except UnsafeURL as e:
                return FetchResult(url, current, redirects=tuple(chain), blocked="unsafe", error=str(e))
            except HostNotFound as e:
                return FetchResult(url, current, redirects=tuple(chain), error=str(e))
            if check_robots and self.respect_robots and not self.allowed(current):
                return FetchResult(url, current, redirects=tuple(chain), blocked="robots",
                                   error="robots.txt does not allow this page")
            self._wait(urlparse(current).netloc)
            try:
                resp = self._session.request(method, current, allow_redirects=False, stream=True, timeout=TIMEOUT)
            except requests.exceptions.SSLError as e:
                return FetchResult(url, current, redirects=tuple(chain), tls_error=True,
                                   error=f"TLS/certificate problem: {type(e).__name__}")
            except requests.RequestException as e:
                return FetchResult(url, current, redirects=tuple(chain), error=type(e).__name__)
            if not self._peer_ok(resp):
                resp.close()
                return FetchResult(url, current, redirects=tuple(chain), blocked="unsafe",
                                   error="connected to a non-public address")
            if resp.is_redirect and resp.headers.get("location"):
                chain.append((current, resp.status_code))
                current = urljoin(current, resp.headers["location"])
                resp.close()
                continue
            return self._read(url, current, resp, tuple(chain), t0)
        return FetchResult(url, current, redirects=tuple(chain), error=f"more than {MAX_REDIRECTS} redirects")

    def _read(self, url: str, final: str, resp: requests.Response, chain, t0: float) -> FetchResult:
        body, truncated = b"", False
        ctype = resp.headers.get("content-type", "")
        try:
            if resp.request.method != "HEAD" and ("html" in ctype or "text" in ctype or "xml" in ctype or not ctype):
                for chunk in resp.iter_content(65536):
                    body += chunk
                    if len(body) > self.max_bytes:
                        body, truncated = body[: self.max_bytes], True
                        break
        except requests.RequestException as e:
            return FetchResult(url, final, resp.status_code, redirects=chain, error=type(e).__name__)
        finally:
            resp.close()
        keep = ("content-type", "last-modified", "x-robots-tag", "strict-transport-security", "server",
                "content-security-policy", "x-frame-options", "x-content-type-options")
        return FetchResult(url, final, resp.status_code,
                           headers={k: v for k, v in resp.headers.items() if k.lower() in keep},
                           text=body.decode(resp.encoding or "utf-8", errors="ignore"), redirects=chain,
                           elapsed_ms=int((time.perf_counter() - t0) * 1000), bytes_read=len(body), truncated=truncated)
