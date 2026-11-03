"""How TechDeva is pitched in a report, shaped to the business's industry and to what the audit saw.

Rules (from the TechDeva sales playbook):
- lead with the outcome for THEIR customers, not with "AI software";
- only offer modules marked "existing" in automation/capabilities.py; "to_confirm" ones stay in the internal brief;
- never promise numbers or quote prices; the 7-day free trial is the only offer;
- the owner stays in control (staff can take over any chat), and their data stays theirs.
"""
from __future__ import annotations

import re

from ..automation.capabilities import CAPABILITIES

BUSY_REVIEWS = 300  # a place with this many Google reviews gets a lot of enquiries

PLAYBOOK: dict[str, dict] = {
    "beauty": {
        "customers": "clients",
        "outcome": "a full appointment book, without anyone glued to the phone",
        "question": "How much is the bridal package, and is Saturday free?",
        "benefits": {
            "whatsapp_ai_agent": "Answers price, package and slot questions on WhatsApp in seconds, day or night, "
                                 "and suggests add-ons like bridal or party packages.",
            "lead_inbox": "Every client who asks is saved with what she wanted, so no bridal or party enquiry is forgotten.",
            "social_publishing": "Your before/after photos turned into ready Instagram and Facebook posts you approve.",
        },
        "care": "",
        "objection": ("Mere clients mujh se baat karna pasand karte hain.",
                      "Bilkul — agent sirf pehla jawab deta hai aur booking pakki karta hai; aap ya staff kisi bhi chat "
                      "mein aa jayein to wo usi waqt peeche hat jata hai."),
        "demo_tip": "Show a bridal-package enquiry at night being answered and booked; use their own service names.",
    },
    "clinics": {
        "customers": "patients",
        "outcome": "every patient enquiry answered and booked, with your doctors fully in control",
        "question": "What is the consultation fee, and can I come tomorrow evening?",
        "benefits": {
            "whatsapp_ai_agent": "Answers fee, timing and treatment questions on WhatsApp in seconds and offers a "
                                 "consultation slot — it never gives medical advice or guarantees.",
            "lead_inbox": "Every patient enquiry saved in one list with the treatment asked about, so your front desk "
                          "can follow up.",
            "social_publishing": "Doctor-approved posts about your treatments, published to Instagram and Facebook.",
        },
        "care": "Medical questions are passed to your doctors; the assistant only answers what you have approved.",
        "objection": ("AI ghalat medical baat keh dega.",
                      "Agent medical mashwara deta hi nahi — sirf fee, timing aur appointment. Medical sawal seedha "
                      "doctor ke paas jata hai, aur aap kisi bhi chat mein khud aa sakte hain."),
        "demo_tip": "Lead with safety: show a medical question being handed to the doctor, then a booking.",
    },
    "academies": {
        "customers": "students and parents",
        "outcome": "every course enquiry turned into an enrolment conversation",
        "question": "When does the next batch start, and what is the fee?",
        "benefits": {
            "whatsapp_ai_agent": "Answers batch dates, fees and timings on WhatsApp in seconds and books a demo class.",
            "lead_inbox": "Every parent or student who asks is saved with the course they want, ready for follow-up "
                          "before the batch fills.",
            "social_publishing": "Results, batch announcements and student stories posted to Instagram and Facebook.",
        },
        "care": "",
        "objection": ("Admission ke liye parents khud aate hain.",
                      "Aate hain — lekin pehle WhatsApp par poochte hain. Jo pehle jawab deta hai, admission wahi leta hai."),
        "demo_tip": "Show a parent asking about the next batch late at night and getting a demo-class slot.",
    },
    "fitness": {
        "customers": "members",
        "outcome": "membership enquiries answered instantly and trial sessions booked",
        "question": "How much is monthly membership, and can I try a session?",
        "benefits": {
            "whatsapp_ai_agent": "Answers membership and class questions on WhatsApp in seconds and books a trial session.",
            "lead_inbox": "Everyone who asked but did not join is saved, so you can win them back.",
            "social_publishing": "Transformations, classes and offers posted to Instagram and Facebook.",
        },
        "care": "",
        "objection": ("Log gym aakar hi join karte hain.",
                      "Aakar join karte hain, lekin pehle message karte hain. Fori jawab = zyada log trial ke liye aate hain."),
        "demo_tip": "Show a membership enquiry turning into a trial-session booking.",
    },
    "veterinary": {
        "customers": "pet owners",
        "outcome": "every pet owner answered quickly and booked in",
        "question": "How much is a vaccination, and can I bring my cat in today?",
        "benefits": {
            "whatsapp_ai_agent": "Answers vaccination, grooming and timing questions on WhatsApp in seconds and offers a slot.",
            "lead_inbox": "Every pet owner who asks is saved, with the pet and the service, for follow-up.",
            "social_publishing": "Pet care tips and happy patients posted to Instagram and Facebook.",
        },
        "care": "Health questions about a pet are passed to your vet.",
        "objection": ("Emergency mein log call karte hain.",
                      "Emergency call hi rahegi — agent routine sawal sambhalta hai taake aap ka phone emergencies ke liye free rahe."),
        "demo_tip": "Show a vaccination enquiry being booked and an urgent case handed to staff.",
    },
    "restaurants": {
        "customers": "guests",
        "outcome": "reservations and catering enquiries answered while the kitchen is busy",
        "question": "Do you have a table for 8 tonight?",
        "benefits": {
            "whatsapp_ai_agent": "Answers menu, timing and table questions on WhatsApp in seconds during the dinner rush.",
            "lead_inbox": "Catering and event enquiries saved in one list so none is missed.",
            "social_publishing": "Dishes and offers posted to Instagram and Facebook.",
        },
        "care": "",
        "objection": ("Hum to delivery apps par hain.",
                      "Apps commission leti hain — direct WhatsApp orders aur reservations aap ke apne customer banate hain."),
        "demo_tip": "Show a table request and a catering enquiry during peak hours.",
    },
    "automotive": {
        "customers": "car owners",
        "outcome": "every service enquiry answered and a bay booked",
        "question": "How much is a full service, and can I bring the car tomorrow morning?",
        "benefits": {
            "whatsapp_ai_agent": "Answers service prices and timings on WhatsApp in seconds and books a slot.",
            "lead_inbox": "Every car owner who asks is saved with the car and the job, for follow-up.",
            "social_publishing": "Before/after detailing photos and offers posted to Instagram and Facebook.",
        },
        "care": "",
        "objection": ("Price gaadi dekh kar hi batate hain.",
                      "Theek hai — agent starting price aur slot deta hai, final price aap gaadi dekh kar batayein."),
        "demo_tip": "Show a service-price question turning into a booked slot.",
    },
    "real_estate": {
        "customers": "buyers and tenants",
        "outcome": "every property enquiry answered and qualified before your agents call",
        "question": "I need a 2-bedroom apartment to rent — what do you have in my budget?",
        "benefits": {
            "whatsapp_ai_agent": "Answers listing questions on WhatsApp in seconds and asks budget, area and timing "
                                 "before an agent calls back.",
            "lead_inbox": "Every buyer and tenant saved with budget and area, so agents call the serious ones first.",
            "social_publishing": "New listings posted to Instagram and Facebook.",
        },
        "care": "",
        "objection": ("Hamare agents khud handle karte hain.",
                      "Agent unhi ke liye kaam karta hai — sawal pooch kar serious leads unhe deta hai, time-wasters nahi."),
        "demo_tip": "Show an enquiry being qualified (budget, area, timing) and handed to a human agent.",
    },
    "driving_schools": {
        "customers": "learners",
        "outcome": "every learner enquiry answered and a first lesson booked",
        "question": "How long is the course, and what is the fee?",
        "benefits": {
            "whatsapp_ai_agent": "Answers course, fee and timing questions on WhatsApp in seconds and books the first lesson.",
            "lead_inbox": "Every learner who asks is saved for follow-up.",
            "social_publishing": "Passed-test stories and offers posted to Instagram and Facebook.",
        },
        "care": "",
        "objection": ("Log phone kar ke hi poochte hain.",
                      "Phone wale bhi WhatsApp par aate hain — wahan fori jawab milega to booking pakki."),
        "demo_tip": "Show a fee question turning into a booked first lesson.",
    },
    "digital_marketing": {
        "customers": "prospective clients",
        "outcome": "every inbound prospect answered fast, so your team spends time on pitches, not inbox",
        "question": "How much is a social media package for my restaurant?",
        "benefits": {
            "whatsapp_ai_agent": "Answers service and package questions on WhatsApp in seconds and books a discovery call.",
            "lead_inbox": "Every prospect saved with what they need and their budget, so no deal goes cold.",
            "social_publishing": "A content gallery and publishing to Instagram and Facebook from one place.",
        },
        "care": "",
        "objection": ("Hum khud marketing agency hain.",
                      "Isi liye — aap clients ke liye leads laate hain, ye aap ke apne leads ko fori jawab deta hai."),
        "demo_tip": "Position as their own sales desk; show a prospect booking a discovery call.",
    },
}
DEFAULT = {
    "customers": "customers",
    "outcome": "every enquiry answered and followed up, even after hours",
    "question": "How much does it cost, and when are you free?",
    "benefits": {
        "whatsapp_ai_agent": "Answers common questions on WhatsApp in seconds, day or night.",
        "lead_inbox": "Every enquiry saved in one list with its source and notes.",
        "social_publishing": "Ready posts for Instagram and Facebook that you approve.",
    },
    "care": "",
    "objection": ("Abhi zaroorat nahi.",
                  "Koi baat nahi — 7 din free chala kar dekh lein, faida na ho to band kar dein."),
    "demo_tip": "Show a late-night enquiry being answered and saved.",
}

CONTROL = ("You stay in control: you or your staff can take over any chat from the dashboard and the assistant "
           "steps back. Your accounts and customer data stay yours.")
TRIAL = "Try it free for 7 days on your own WhatsApp. If it does not help, you simply stop — no cost."


def _angle(profile: dict, a4: dict, book: dict) -> dict:
    """The one reason this business should care first, chosen from what the audit actually saw."""
    tools = a4.get("existing_automation") or []
    kinds = {t["kind"] for t in tools}
    competitors = [t["name"] for t in tools if t.get("competitor")]
    sig = a4.get("signals") or {}
    reviews = profile.get("review_count") or 0
    who = book["customers"]
    if competitors:
        names = ", ".join(competitors[:2])
        return {"key": "alongside", "seen": f"Already uses {names}",
                "line": f"You already use {names}. TechDeva works alongside it and covers what it does not: "
                        f"answering {who} on WhatsApp the moment they write."}
    if reviews >= BUSY_REVIEWS:
        return {"key": "busy", "seen": f"{reviews} Google reviews",
                "line": f"With {reviews} Google reviews you are clearly busy — and busy teams reply late. "
                        f"TechDeva answers {who} instantly so none of them goes to the next place."}
    if sig.get("whatsapp_links") and "whatsapp_tool" not in kinds:
        return {"key": "speed", "seen": "WhatsApp link on the website, no WhatsApp tool",
                "line": f"Your website already sends {who} to WhatsApp. Today someone has to answer each one by hand; "
                        "TechDeva answers in seconds, any hour."}
    if not sig.get("whatsapp_links") and a4.get("evaluation_status") == "completed":
        return {"key": "new_channel", "seen": "No WhatsApp on the website",
                "line": f"Most {who} today want to message, not call. A WhatsApp button answered by TechDeva "
                        "opens that door without adding staff."}
    return {"key": "capture", "seen": "General",
            "line": f"TechDeva makes sure every one of your {who} who asks gets an answer and is saved for follow-up."}


def _benefits(a4: dict, book: dict, only_existing: bool) -> list[dict]:
    out, used = [], set()
    for o in a4.get("opportunities") or []:
        cap = o["techdeva_capability"]
        cid = cap.get("id")
        if not cid or cid in used or (only_existing and cap.get("status") != "existing"):
            continue
        used.add(cid)
        out.append({"because": o["business_problem"], "module": CAPABILITIES[cid]["name"],
                    "what": book["benefits"].get(cid) or DEFAULT["benefits"].get(cid) or CAPABILITIES[cid]["name"],
                    "status": cap.get("status")})
    return out


def owner_pitch(profile: dict, a4: dict) -> dict | None:
    """'How TechDeva can help' for the owner report, or None when no live module fits what we saw."""
    book = PLAYBOOK.get(profile.get("industry") or "", DEFAULT)
    benefits = _benefits(a4, book, only_existing=True)
    if not benefits:
        return None
    angle = _angle(profile, a4, book)
    return {"headline": f"How TechDeva can help {profile['name']}: {book['outcome']}.",
            "intro": angle["line"], "benefits": benefits,
            "example": f"Example: someone writes at 11 pm, \"{book['question']}\" — the assistant replies right away "
                       "and the enquiry is saved for your team in the morning.",
            "care": book["care"], "control": CONTROL, "cta": TRIAL}


# Proposal email (Harvey): only findings the audit saw itself, reworded for an owner. Order = how much an owner cares.
PLAIN_FINDINGS: list[tuple[re.Pattern, str, str]] = [  # (pattern, owner wording, topic); best first
    (re.compile(r"(\w+) page tells Google not to list it", re.I),
     "your {0} page is set to stay hidden from Google, so people searching for you won't find it", "google"),
    (re.compile(r"Website does not use HTTPS"), "browsers mark your website as \"not secure\" because it has no HTTPS",
     "secure"),
    (re.compile(r"Main content takes ([\d.]+)s to appear", re.I), "your homepage takes about {0} seconds to show on a computer",
     "speed"),
    (re.compile(r"Homepage HTML took ([\d.]+)s to arrive", re.I), "your homepage takes over {0} seconds to start loading",
     "speed"),
    (re.compile(r"No call, WhatsApp or booking button on the first phone screen"),
     "on a phone, there is no call, WhatsApp or booking button on the first screen", "mobile"),
    (re.compile(r"Broken link"), "some links on your website lead to pages that don't open", "links"),
    (re.compile(r"Homepage downloads ([\d.]+) MB"), "your homepage downloads {0} MB, which is slow on mobile data", "speed"),
    (re.compile(r"Page is wider than a phone screen"), "on a phone, your pages scroll sideways", "mobile"),
    (re.compile(r"Page content jumps around while loading"),
     "your page jumps around while it loads, which makes it hard to tap the right button", "mobile"),
    (re.compile(r"No tap-to-call phone link"), "your phone number can't be tapped to call on a mobile", "mobile"),
    (re.compile(r"No contact or enquiry form"), "there is no enquiry form on the pages we checked", "form"),
]


def _plain(issue: str) -> str:
    for pattern, text, _ in PLAIN_FINDINGS:
        if m := pattern.search(issue):
            return text.format(*(g.lower() for g in m.groups()))
    return ""


def proposal(profile: dict, dataset: dict, a4: dict) -> dict:
    """What Harvey's proposal email says about this business: two seen findings and one TechDeva line.
    Empty findings when fewer than two are usable, so Harvey keeps its general email."""
    seen = [i for i in dataset.get("issues", []) if i.get("status") == "verified"]
    ranked = sorted(((n, topic, _plain(i["issue"])) for i in seen for n, (p, _, topic) in enumerate(PLAIN_FINDINGS)
                     if p.search(i["issue"])), key=lambda x: x[0])
    by_topic: dict[str, str] = {}  # one finding per topic: two speed numbers read like one point
    for _, topic, text in ranked:
        if text:
            by_topic.setdefault(topic, text)
    findings = list(by_topic.values())[:2]
    book = PLAYBOOK.get(profile.get("industry") or "", DEFAULT)
    owner = owner_pitch(profile, a4)
    line = owner["intro"] if owner else (f"TechDeva helps with {book['outcome']}: it answers {book['customers']} "
                                         "on WhatsApp in seconds and saves every enquiry for your team.")
    if owner and owner.get("care"):
        line = f"{line} {owner['care']}"
    return {"finding_1": findings[0] if len(findings) == 2 else "",
            "finding_2": findings[1] if len(findings) == 2 else "", "techdeva_line": line}


def internal_pitch(profile: dict, a4: dict) -> dict:
    """Pitch angle and talk track for the caller. Proposed modules are listed apart and must not be promised."""
    book = PLAYBOOK.get(profile.get("industry") or "", DEFAULT)
    all_fit = _benefits(a4, book, only_existing=False)
    angle = _angle(profile, a4, book)
    they_say, answer = book["objection"]
    return {"angle": angle["key"], "angle_seen": angle["seen"], "angle_line": angle["line"],
            "outcome": book["outcome"], "demo_tip": book["demo_tip"],
            "offer": [b for b in all_fit if b["status"] == "existing"],
            "do_not_promise": [b["module"] for b in all_fit if b["status"] != "existing"],
            "likely_objection": {"they_say": they_say, "answer": answer},
            "close": "Ask for the 7-day free trial on their own WhatsApp — no prices on the first call."}
