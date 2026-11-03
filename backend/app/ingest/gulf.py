"""Gulf + South Asia geography and industry search terms (copied from leadgen/leadgen/config.py, 31 Oct 2026).

leadgen/ stays independent; change both if a city or search term changes.
"""
from __future__ import annotations

INDUSTRIES: dict[str, dict] = {
    "beauty": {
        "label": "Beauty salons & spas",
        "tier": 1,
        "search_terms": ["beauty salon", "ladies salon", "hair salon", "nail salon", "spa", "barbershop"],
        "osm": ['shop~"^(beauty|hairdresser|massage)$"', 'leisure="spa"'],
    },
    "clinics": {
        "label": "Medical, dental & aesthetic clinics",
        "tier": 1,
        "search_terms": ["dental clinic", "aesthetic clinic", "dermatology clinic", "physiotherapy clinic",
                           "medical clinic", "polyclinic"],
        "osm": ['amenity~"^(dentist|clinic|doctors)$"', 'healthcare~"^(dentist|clinic|doctor|physiotherapist|centre)$"'],
    },
    "academies": {
        "label": "Training centres & academies",
        "tier": 1,
        "search_terms": ["training institute", "tutoring centre", "language school", "music school",
                           "dance academy", "coaching centre"],
        "osm": ['amenity~"^(language_school|music_school|training|prep_school|tutoring|dancing_school)$"',
                'office="educational_institution"', 'leisure="dance"'],
    },
    "fitness": {
        "label": "Gyms & fitness studios",
        "tier": 2,
        "search_terms": ["gym", "fitness studio", "yoga studio", "martial arts academy", "pilates studio"],
        "osm": ['leisure~"^(fitness_centre|sports_centre)$"'],
    },
    "veterinary": {
        "label": "Vet clinics & pet grooming",
        "tier": 2,
        "search_terms": ["veterinary clinic", "pet grooming"],
        "osm": ['amenity="veterinary"', 'shop="pet_grooming"'],
    },
    "restaurants": {
        "label": "Restaurants & cafes",
        "tier": 3,
        "search_terms": ["restaurant", "cafe"],
        "osm": ['amenity~"^(restaurant|cafe)$"'],
    },
    "automotive": {
        "label": "Car service & detailing",
        "tier": 3,
        "search_terms": ["car service center", "car detailing", "auto repair"],
        "osm": ['shop~"^(car_repair|tyres)$"', 'amenity="car_wash"'],
    },
    "real_estate": {
        "label": "Real estate agencies",
        "tier": 3,
        "search_terms": ["real estate agency"],
        "osm": ['office="estate_agent"'],
    },
    "driving_schools": {
        "label": "Driving schools",
        "tier": 2,
        "search_terms": ["driving school"],
        "osm": ['amenity="driving_school"'],
    },
    "digital_marketing": {
        "label": "Digital marketing agencies",
        "tier": 2,
        "search_terms": ["digital marketing agency", "marketing agency", "social media marketing agency",
                           "advertising agency", "SEO agency"],
        "osm": ['office~"^(advertising_agency|marketing)$"'],
    },
}
PHASE1_INDUSTRIES = ["beauty", "clinics", "academies"]

# ---------------------------------------------------------------- geography
# bbox = (south, west, north, east)
COUNTRIES: dict[str, dict] = {
    "AE": {"name": "UAE", "cities": {
        "Dubai": (24.85, 54.90, 25.36, 55.60),
        "Abu Dhabi": (24.25, 54.30, 24.55, 54.75),
        "Al Ain": (24.10, 55.60, 24.30, 55.85),
        "Sharjah": (25.25, 55.35, 25.42, 55.60),
        "Ajman": (25.36, 55.42, 25.47, 55.57),
        "Umm Al Quwain": (25.50, 55.53, 25.60, 55.70),
        "Ras Al Khaimah": (25.60, 55.85, 25.85, 56.05),
        "Fujairah": (25.05, 56.28, 25.20, 56.38),
    }},
    "SA": {"name": "Saudi Arabia", "cities": {
        "Riyadh": (24.45, 46.50, 24.95, 46.95),
        "Jeddah": (21.35, 39.10, 21.75, 39.30),
        "Dammam": (26.35, 49.95, 26.50, 50.15),
        "Khobar": (26.15, 50.15, 26.35, 50.25),
        "Mecca": (21.33, 39.73, 21.50, 39.95),
        "Medina": (24.40, 39.50, 24.55, 39.70),
        "Taif": (21.20, 40.35, 21.35, 40.50),
        "Abha": (18.18, 42.45, 18.28, 42.57),
    }},
    "QA": {"name": "Qatar", "cities": {
        "Doha": (25.20, 51.40, 25.40, 51.60),
        "Al Rayyan": (25.22, 51.30, 25.35, 51.40),
        "Al Wakrah": (25.13, 51.57, 25.20, 51.63),
        "Al Khor": (25.65, 51.47, 25.72, 51.53),
    }},
    "KW": {"name": "Kuwait", "cities": {
        "Kuwait City": (29.33, 47.90, 29.40, 48.02),
        "Hawalli & Salmiya": (29.30, 48.00, 29.36, 48.10),
        "Farwaniya": (29.24, 47.90, 29.30, 48.00),
        "Ahmadi & Fahaheel": (29.05, 48.05, 29.15, 48.17),
        "Jahra": (29.30, 47.62, 29.38, 47.72),
    }},
    "BH": {"name": "Bahrain", "cities": {
        "Manama": (26.18, 50.53, 26.25, 50.62),
        "Muharraq": (26.23, 50.58, 26.30, 50.67),
        "Riffa": (26.08, 50.52, 26.15, 50.60),
        "Isa Town & Hamad Town": (26.12, 50.45, 26.18, 50.56),
    }},
    "OM": {"name": "Oman", "cities": {
        "Muscat": (23.55, 58.10, 23.65, 58.60),
        "Seeb": (23.62, 58.05, 23.72, 58.20),
        "Sohar": (24.30, 56.65, 24.40, 56.78),
        "Salalah": (16.98, 54.00, 17.06, 54.15),
        "Nizwa": (22.90, 57.50, 22.97, 57.57),
    }},
    # South Asia (added 31 Oct 2026: Urdu / Hindi / some English is normal, same as the Gulf teams speak)
    "PK": {"name": "Pakistan", "region": "South Asia", "cities": {
        "Karachi": (24.75, 66.90, 25.10, 67.30),
        "Lahore": (31.35, 74.15, 31.65, 74.50),
        "Islamabad": (33.60, 72.90, 33.78, 73.20),
        "Rawalpindi": (33.52, 72.95, 33.68, 73.15),
        "Faisalabad": (31.33, 72.98, 31.50, 73.20),
        "Multan": (30.12, 71.38, 30.28, 71.58),
        "Peshawar": (33.92, 71.45, 34.08, 71.62),
        "Hyderabad": (25.30, 68.30, 25.45, 68.42),
        "Sialkot": (32.45, 74.45, 32.55, 74.58),
        "Gujranwala": (32.10, 74.10, 32.25, 74.25),
        "Quetta": (30.13, 66.93, 30.27, 67.07),
    }},
    "IN": {"name": "India", "region": "South Asia", "cities": {
        "Delhi": (28.40, 76.85, 28.88, 77.35),
        "Mumbai": (18.89, 72.77, 19.27, 72.99),
        "Bengaluru": (12.83, 77.46, 13.14, 77.78),
        "Hyderabad": (17.25, 78.30, 17.55, 78.65),
        "Chennai": (12.90, 80.12, 13.23, 80.32),
        "Kolkata": (22.45, 88.25, 22.65, 88.45),
        "Pune": (18.42, 73.75, 18.63, 73.98),
        "Ahmedabad": (22.95, 72.48, 23.12, 72.68),
        "Jaipur": (26.80, 75.70, 27.00, 75.90),
        "Lucknow": (26.75, 80.85, 26.95, 81.05),
        "Chandigarh": (30.65, 76.70, 30.80, 76.85),
        "Gurugram": (28.38, 76.95, 28.52, 77.12),
        "Noida": (28.48, 77.30, 28.65, 77.45),
    }},
}
for _c in COUNTRIES.values():
    _c.setdefault("region", "Gulf")
REGIONS = list(dict.fromkeys(c["region"] for c in COUNTRIES.values()))


def expand_targets(countries: str, cities: str = "all") -> list[tuple[str, str]]:
    """'gulf' or 'AE,SA' + 'all' or 'Dubai,Riyadh' -> [(cc, city), ...]."""
    key = countries.strip().lower()
    if key == "all":
        ccs = list(COUNTRIES)
    elif key in ("gulf", "gcc"):
        ccs = [cc for cc, c in COUNTRIES.items() if c["region"] == "Gulf"]
    else:
        ccs = []
        for c in countries.split(","):
            c = c.strip()
            cc = c.upper() if c.upper() in COUNTRIES else next(
                (k for k, v in COUNTRIES.items() if v["name"].lower() == c.lower()), None)
            if not cc:
                raise SystemExit(f"Unknown country {c!r}. Use: gulf, or any of {', '.join(COUNTRIES)}")
            ccs.append(cc)
    wanted = [x.strip().lower() for x in (cities or "all").split(",") if x.strip()]
    out = []
    for cc in ccs:
        for name in COUNTRIES[cc]["cities"]:
            if "all" in wanted or name.lower() in wanted:
                out.append((cc, name))
    if not out:
        raise SystemExit(f"No city matched {cities!r} in {', '.join(ccs)}. Run `run.bat list` to see cities.")
    return out


def find_city(country: str, city: str) -> tuple[str, str, tuple]:
    cc = country.upper()
    if cc not in COUNTRIES:
        for k, v in COUNTRIES.items():
            if v["name"].lower() == country.lower():
                cc = k
                break
    if cc not in COUNTRIES:
        raise SystemExit(f"Unknown country {country!r}. Use one of: {', '.join(COUNTRIES)}")
    for name, bbox in COUNTRIES[cc]["cities"].items():
        if name.lower() == city.lower():
            return cc, name, bbox
    raise SystemExit(f"Unknown city {city!r} for {cc}. Use one of: {', '.join(COUNTRIES[cc]['cities'])}")
