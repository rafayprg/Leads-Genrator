"""7.2 HTML and 7.3 PDF for a report package. HTML is self-contained (screenshots embedded) and prints well."""
from __future__ import annotations

import base64
from pathlib import Path

from jinja2 import Environment, select_autoescape

TEMPLATE = r"""<!doctype html><html lang="{{ 'ur-Latn' if p.language == 'roman_urdu' else 'en' }}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ o.name }} — {{ L.title_owner if p.audience == 'owner' else L.title_internal }}</title>
<style>
:root{--ink:#111827;--mute:#6b7280;--line:#e5e7eb;--acc:#16a34a;--acc2:#0891b2;--bad:#dc2626;--warn:#d97706;--soft:#f9fafb}
*{box-sizing:border-box}body{margin:0;font:14px/1.55 Inter,"Segoe UI",system-ui,sans-serif;color:var(--ink);background:#fff}
main{max-width:860px;margin:0 auto;padding:36px 28px}
header{border-bottom:3px solid var(--acc);padding-bottom:14px;margin-bottom:22px}
.brand{font-weight:700;letter-spacing:.04em;color:var(--acc2);font-size:12px;text-transform:uppercase}
h1{font-size:26px;margin:6px 0 2px}h2{font-size:18px;margin:28px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.mute{color:var(--mute)}.small{font-size:12px}
.meta{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:6px 18px;margin-top:10px}
.summary{background:var(--soft);border-left:4px solid var(--acc);padding:12px 16px;border-radius:6px}
table{width:100%;border-collapse:collapse;margin:8px 0}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--mute);font-weight:600}
.tag{display:inline-block;font-size:11px;padding:1px 8px;border-radius:99px;border:1px solid var(--line);color:var(--mute);white-space:nowrap}
.High{color:#fff;background:var(--bad);border-color:var(--bad)}.Medium{color:#fff;background:var(--warn);border-color:var(--warn)}
.ok{color:var(--acc);border-color:#bbf7d0}.confirm{color:var(--warn);border-color:#fde68a}
.rec{border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:8px 0;break-inside:avoid}
.rec b{display:block;margin:4px 0}.shots{display:flex;gap:14px;align-items:flex-start}.shots img{border:1px solid var(--line);border-radius:6px;width:100%}
.shots figure{margin:0;flex:1}.shots figure.m{flex:0 0 26%}
.note{font-size:12px;color:var(--mute);border-top:1px solid var(--line);margin-top:28px;padding-top:10px}
a{color:var(--acc2)}
.pitch{border:1px solid #bbf7d0;background:#f0fdf4;border-radius:8px;padding:12px 16px;break-inside:avoid}
.pitch .lead{font-size:16px;font-weight:600;margin-top:0}.benefit{border-left:3px solid var(--acc);padding:4px 10px;margin:8px 0}
.example{font-style:italic;color:var(--mute)}.cta{font-weight:600;color:var(--acc);margin-bottom:0}
@media print{main{padding:0}h2{break-after:avoid}.rec{break-inside:avoid}a{color:var(--ink)}}
</style></head><body><main>
<header><div class="brand">TechDeva · {{ L.brand_owner if p.audience == 'owner' else L.brand_internal }}</div>
<h1>{{ o.name }}</h1>
<div class="meta small">
<div><span class="mute">{{ L.business_id }}</span> {{ o.business_id }}</div>
<div><span class="mute">{{ L.type }}</span> {{ o.category or o.industry or '—' }}</div>
<div><span class="mute">{{ L.location }}</span> {{ o.location or '—' }}{% if o.country %}, {{ o.country }}{% endif %}</div>
<div><span class="mute">{{ L.audit_date }}</span> {{ p.generated_at[:10] }}</div>
<div><span class="mute">{{ L.website }}</span> {% if o.website %}<a href="{{ o.website | safe_url }}">{{ o.website }}</a>{% else %}—{% endif %}</div>
<div><span class="mute">{{ L.phone }}</span> {{ o.phone or '—' }}</div>
{% if o.rating %}<div><span class="mute">{{ L.rating }}</span> {{ o.rating }}★ ({{ o.review_count or 0 }} {{ L.reviews }})</div>{% endif %}
{% if o.social_profiles %}<div><span class="mute">Social</span> {% for s in o.social_profiles %}<a href="{{ s.url | safe_url }}">{{ s.platform }}</a>{% if not loop.last %} · {% endif %}{% endfor %}</div>{% endif %}
</div></header>

<h2>1. {{ L.summary }}</h2><p class="summary">{{ s.executive_summary }}</p>{% if p.wording == 'ai' %}<p class="small mute">{{ L.ai_note }}</p>{% endif %}

<h2>2. {{ L.fix_first }}</h2>
{% for r in s.recommendations %}
<div class="rec"><span class="tag {{ r.priority }}">{{ L[r.priority] }}</span>
{% if r.confirmed %}<span class="tag ok">{{ L.seen }}</span>{% else %}<span class="tag confirm">{{ L.confirm if p.audience == 'owner' else L.confirm_internal }}</span>{% endif %}
<b>{{ r.issue }}</b>
{% if r.why %}<div><span class="mute">{{ L.why }}</span> {{ r.why }}</div>{% endif %}
{% if r.fix %}<div><span class="mute">{{ L.what }}</span> {{ r.fix }}</div>{% endif %}
</div>
{% else %}<p class="mute">{{ L.nothing }}</p>{% endfor %}

<h2>3. {{ L.website }}</h2>
{% set w = s.website %}
<p>{% if w.pages_inspected %}We inspected {{ w.pages_inspected }} page(s).{% else %}The website check did not complete ({{ w.status }}).{% endif %}</p>
{% if w.pages_inspected %}<table>
<tr><td class="mute">Homepage arrived in</td><td>{{ w.metrics.html_seconds }} s</td><td class="mute">Main content visible</td><td>{{ w.metrics.main_content_seconds or '—' }} s</td></tr>
<tr><td class="mute">Page weight</td><td>{{ w.metrics.page_weight_mb or '—' }} MB</td><td class="mute">Call/book buttons on first phone screen</td><td>{{ w.metrics.phone_cta_first_screen if w.metrics.phone_cta_first_screen is not none else '—' }}</td></tr>
</table>{% endif %}
{% if shots %}<div class="shots">{% if shots.desktop %}<figure><img src="{{ shots.desktop }}" alt="Homepage on a computer"><figcaption class="small mute">Computer</figcaption></figure>{% endif %}
{% if shots.mobile %}<figure class="m"><img src="{{ shots.mobile }}" alt="Homepage on a phone"><figcaption class="small mute">Phone</figcaption></figure>{% endif %}</div>{% endif %}
{% if w.issues %}<table><tr><th>Priority</th><th>Finding</th></tr>{% for r in w.issues %}<tr><td><span class="tag {{ r.priority }}">{{ r.priority }}</span></td><td>{{ r.issue }}</td></tr>{% endfor %}</table>{% endif %}

<h2>4. {{ L.social }}</h2>
{% if s.social.profiles %}<table><tr><th>Platform</th><th>Account</th>{% if p.audience == 'internal' %}<th>Confidence</th>{% endif %}</tr>
{% for x in s.social.profiles %}<tr><td>{{ x.platform }}</td><td><a href="{{ x.profile_url | safe_url }}">{{ x.profile_url }}</a></td>{% if p.audience == 'internal' %}<td>{{ x.confidence }}</td>{% endif %}</tr>{% endfor %}</table>
{% else %}<p>No official social media account was found on the website.</p>{% endif %}
{% for r in s.social.issues %}<p>• {{ r.issue }}</p>{% endfor %}
<p class="small mute">{{ s.social.not_available }}</p>

<h2>5. {{ L.tools }}</h2>
{% set a = s.automation %}
{% if a.tools_in_use %}<p>Tools seen on the website: {{ a.tools_in_use | join(', ') }}.</p>{% endif %}
{% if a.opportunities %}<table><tr><th>What looks manual today</th><th>What could be automated</th>{% if p.audience == 'internal' %}<th>TechDeva</th>{% endif %}</tr>
{% for x in a.opportunities %}<tr><td>{{ x.problem }}</td><td>{{ x.suggestion }}</td>{% if p.audience == 'internal' %}<td>{{ x.techdeva.name }}<br><span class="tag {{ 'ok' if x.techdeva.status == 'existing' else 'confirm' }}">{{ x.techdeva.offer }}</span></td>{% endif %}</tr>{% endfor %}</table>
<p class="small mute">Seen from outside only; nothing was tested on the business's systems and no impact is claimed.</p>{% else %}<p class="mute">No automation gaps were identified{% if a.status != 'completed' %} (check status: {{ a.status }}){% endif %}.</p>{% endif %}

{% set tp = s.techdeva_pitch %}
{% if tp %}
<h2>6. {{ L.help }}</h2>
<div class="pitch"><p class="lead">{{ tp.headline }}</p><p>{{ tp.intro }}</p>
{% for b in tp.benefits %}<div class="benefit"><div class="small mute">{{ L.because }} {{ b.because }}</div><b>{{ b.what }}</b></div>{% endfor %}
<p class="example">{{ tp.example }}</p>
{% if tp.care %}<p class="small">{{ tp.care }}</p>{% endif %}
<p class="small">{{ tp.control }}</p>
<p class="cta">{{ tp.cta }}</p></div>
{% endif %}

{% if p.audience == 'internal' %}
<h2>6. Sales notes (internal)</h2>
{% set pc = s.pitch %}
<div class="pitch"><p><b>Lead with ({{ pc.angle | replace('_', ' ') }}):</b> {{ pc.angle_line }} <span class="small mute">— based on: {{ pc.angle_seen }}</span></p>
<p><b>Outcome to sell:</b> {{ pc.outcome }}</p>
<p><b>Demo:</b> {{ pc.demo_tip }}</p>
{% if pc.offer %}<p><b>Offer:</b></p>{% for b in pc.offer %}<div class="benefit"><div class="small mute">{{ b.because }}</div><b>{{ b.module }}</b> — {{ b.what }}</div>{% endfor %}{% endif %}
{% if pc.do_not_promise %}<p class="small"><b>Do not promise yet (not live):</b> {{ pc.do_not_promise | join(' · ') }}</p>{% endif %}
<p><b>Likely objection:</b> “{{ pc.likely_objection.they_say }}” → {{ pc.likely_objection.answer }}</p>
<p class="cta">{{ pc.close }}</p></div>
{% set op = s.opportunities %}
<p><b>Suggested first topic:</b> {{ op.suggested_first_topic or '—' }}</p>
{% if op.competitor_tools %}<p><b>Already pays for:</b> {{ op.competitor_tools | join(', ') }} — weaker lead or needs a switch story.</p>{% endif %}
{% if op.techdeva_modules %}<table><tr><th>Module</th><th>Offer</th><th>Because</th></tr>{% for m in op.techdeva_modules %}<tr><td>{{ m.module }}</td><td>{{ m.offer }}</td><td>{{ m.because }}</td></tr>{% endfor %}</table>{% endif %}
<p class="small mute">{{ op.note }}</p>
{% if s.needs_verification %}<p><b>Check before the call ({{ s.needs_verification | length }}):</b> {% for r in s.needs_verification %}{{ r.issue }}{% if not loop.last %} · {% endif %}{% endfor %}</p>{% endif %}
{% endif %}

<h2>{{ 7 if p.audience == 'internal' or tp else 6 }}. {{ L.evidence }}</h2>
{% set e = s.evidence_limitations %}
<table><tr><th>Part</th><th>Status</th><th>Note</th></tr>{% for r in e.completeness %}<tr><td>{{ r.section }}</td><td>{{ r.status | replace('_', ' ') }}</td><td class="small">{{ r.reason }}</td></tr>{% endfor %}</table>
{% for c in e.contradictions %}<p class="small">⚠ {{ c.statement }}</p>{% endfor %}
{% if e.sources.website_pages %}<p class="small"><b>Pages inspected:</b> {% for k, u in e.sources.website_pages.items() %}{{ k }} ({{ u }}){% if not loop.last %}, {% endif %}{% endfor %}</p>{% endif %}
{% if p.audience == 'internal' and e.left_out %}<p class="small"><b>Left out (no evidence / stale):</b> {{ e.left_out | join(' · ') }}</p>{% endif %}
<p class="note">{{ L.footer | replace("{date}", p.generated_at[:10]) }}</p>
</main></body></html>"""

ALLOWED_LINK = ("http://", "https://")


def safe_url(url: str | None) -> str:
    """Scraped links only become clickable when they are plain web addresses (no javascript:, data:, ...)."""
    return url if isinstance(url, str) and url.lower().startswith(ALLOWED_LINK) else "#"


_env = Environment(autoescape=select_autoescape(default=True))
_env.filters["safe_url"] = safe_url
_template = _env.from_string(TEMPLATE)


def _data_uri(folder: Path, name: str) -> str:
    """Screenshot as a data URI: .jpg since 31 Oct, .png for audits made before that."""
    for suffix, mime in ((".jpg", "image/jpeg"), (".png", "image/png")):
        path = folder / f"{name}{suffix}"
        if path.is_file():
            return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
    return ""


LABELS = {
    "en": {
        "title_owner": "Digital audit", "title_internal": "Internal sales brief",
        "brand_owner": "Business digital audit", "brand_internal": "Internal sales brief — not for the client",
        "business_id": "Business ID", "type": "Type", "location": "Location", "audit_date": "Audit date",
        "website": "Website", "phone": "Phone", "rating": "Google rating", "reviews": "reviews",
        "summary": "Summary", "fix_first": "What to fix first", "High": "High priority", "Medium": "Medium priority",
        "Low": "Low priority", "seen": "seen directly", "confirm": "please confirm",
        "confirm_internal": "not confirmed — check on the call", "why": "Why it matters:", "what": "What to do:",
        "nothing": "Nothing to fix was found.", "social": "Social media", "tools": "Tools and automation",
        "evidence": "Evidence & limitations", "help": "How TechDeva can help", "because": "Because:",
        "ai_note": "Summary worded with AI from the checked facts below; every number was matched to the facts.",
        "footer": ("Prepared by TechDeva from publicly available information on {date}. Findings marked "
                   "\"please confirm\" were inferred from outside and may differ from how the business actually works. "
                   "No private data, logins or business systems were accessed."),
    },
    "roman_urdu": {
        "title_owner": "Digital audit", "title_internal": "Internal sales brief",
        "brand_owner": "Business ka digital audit", "brand_internal": "Internal sales brief — client ke liye nahi",
        "business_id": "Business ID", "type": "Qisam", "location": "Jagah", "audit_date": "Audit ki tareekh",
        "website": "Website", "phone": "Phone", "rating": "Google rating", "reviews": "reviews",
        "summary": "Khulasa", "fix_first": "Pehle kya theek karein", "High": "Zyada zaroori",
        "Medium": "Darmiyana zaroori", "Low": "Kam zaroori", "seen": "khud dekha gaya",
        "confirm": "baraye meharbani confirm karein", "confirm_internal": "confirm nahi — call par poochein",
        "why": "Kyun zaroori hai:", "what": "Kya karein:", "nothing": "Theek karne wali koi cheez nahi mili.",
        "social": "Social media", "tools": "Tools aur automation", "evidence": "Saboot aur hudood",
        "help": "TechDeva kaise madad kar sakta hai", "because": "Kyun ke:",
        "ai_note": "Yeh khulasa AI ne neeche diye gaye check shuda facts se likha hai; har number facts se milaya gaya.",
        "footer": ("TechDeva ne yeh report {date} ko sirf public maloomat se tayyar ki. \"Confirm karein\" wali baatein "
                   "bahar se andaza hain aur asal kaam ke tareeqe se mukhtalif ho sakti hain. Koi private data, login ya "
                   "business ka system istemal nahi hua."),
    },
}


def html(package: dict, screenshots_dir: Path | None = None) -> str:
    shots = {}
    if screenshots_dir is not None:
        for name in package["sections"]["website"].get("screenshots") or []:
            uri = _data_uri(screenshots_dir, name)
            if uri:
                shots[name] = uri
    labels = LABELS.get(package.get("language", "en"), LABELS["en"])
    return _template.render(p=package, s=package["sections"], o=package["sections"]["overview"], shots=shots, L=labels)


def pdf(html_text: str, out: Path) -> str:
    """Print the HTML with the Chromium used by Agent 1. Returns "" or the reason it could not."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                ctx = browser.new_context(java_script_enabled=False)
                ctx.route("**/*", lambda route: route.abort() if not route.request.url.startswith("data:") else route.continue_())
                page = ctx.new_page()
                page.set_content(html_text, wait_until="load")
                page.pdf(path=str(out), format="A4", print_background=True,
                         margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
            finally:
                browser.close()
        return ""
    except Exception as e:  # PDF is a convenience; the HTML report still exists
        return f"PDF not made: {type(e).__name__}: {str(e).splitlines()[0][:150]}"
