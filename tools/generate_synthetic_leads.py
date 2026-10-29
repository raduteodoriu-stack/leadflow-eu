#!/usr/bin/env python3
"""Generate the LF-005 synthetic dataset for LeadFlow EU.

Builds 100 inbound enquiry events for the fictional vendor MoP Cloud, the
follow-up activities that belong to them, and the expected outcome of every
event under LF-RULES-v1.0.

How the expected outcomes are produced
--------------------------------------
Outcome first: every new lead is built from a recipe that states the result
it must produce (for example "high fit + low engagement -> P2, rule 5"), and
its inputs are chosen to match. A small reference calculation in this file
checks every recipe and works out the state of returning contacts. It shares
no code with the routing engine (LF-006/LF-007), so it can be used to test it.
The hand-reviewed LF-004 scenarios remain the primary acceptance reference.

Usage (from the repository root, Python 3.9+, standard library only):
    python3 tools/generate_synthetic_leads.py           # write the files
    python3 tools/generate_synthetic_leads.py --check   # fail if files are out of date
"""
from __future__ import annotations

import argparse
import copy
import itertools
import json
import pathlib
import random
import re
import sys
import unicodedata
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
SEED = 20261023
RULE_VERSION = "LF-RULES-v1.0"
SOURCE_SYSTEM = "synthetic_fixture"
MAD = ZoneInfo("Europe/Madrid")
UTC = timezone.utc
ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_FILE = "data/synthetic/leads_100.json"
EXPECTED_FILE = "data/synthetic/expected_outcomes.json"
DOC_FILE = "docs/synthetic_dataset.md"

PERIOD_START = date(2026, 10, 12)
PERIOD_END = date(2026, 11, 6)
CUTOFF = datetime(2026, 11, 6, 18, 0, tzinfo=MAD)
WINDOW = timedelta(hours=30 * 24)
SLA_MINUTES = 480
TARGET_MINUTES = {"P1": 60, "P2": 240, "P3": 480}
PRIORITY_RANK = {"P1": 1, "P2": 2, "P3": 3}
RECONTACT_MINUTES = 480


_UNSET = object()  # marks "choose a country input for me"


def _mad(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=MAD)


REPS = {"ES": ["ES-01", "ES-02"], "PT": ["PT-01", "PT-02"], "FR": ["FR-01", "FR-02"]}
INITIAL_ROTATION = {"ES": "ES-01", "PT": "PT-01", "FR": "FR-01"}
UNAVAILABLE = [
    {"rep": "PT-01", "from": _mad(2026, 10, 21), "until": _mad(2026, 10, 22), "reason": "Portugal team offsite"},
    {"rep": "PT-02", "from": _mad(2026, 10, 21), "until": _mad(2026, 10, 22), "reason": "Portugal team offsite"},
    {"rep": "ES-01", "from": _mad(2026, 10, 28), "until": _mad(2026, 10, 29), "reason": "Day off"},
    {"rep": "FR-02", "from": _mad(2026, 11, 2), "until": None, "reason": "Left the team"},
]
REDIRECT_RULES = {
    "ES": {"supplier_code": "SUP-ES-01", "supplier_name": "Synthetic Panel Partner ES",
           "destination_url": "https://panel-partner-es.example/join"},
    "FR": {"supplier_code": "SUP-FR-01", "supplier_name": "Synthetic Panel Partner FR",
           "destination_url": "https://panel-partner-fr.example/rejoindre"},
}

GROUP_TARGETS = {
    "new_buyer_assignable": 55,
    "returning_contact": 10,
    "supplier_or_both": 7,
    "relationship_unknown": 3,
    "blocking_exception": 12,
    "ambiguous_identity": 2,
    "participant": 5,
    "replay": 3,
    "malformed": 3,
}

# ---------------------------------------------------------------------------
# Scoring tables (LF-002) and allowed values (data dictionary)
# ---------------------------------------------------------------------------
CORE = ["market_research", "polling", "research_consultancy", "panel_sample_provider"]
ADJACENT = ["research_technology", "advertising_media_pr_agency", "ux_research_agency", "management_consultancy"]
CONNECTED = ["consumer_goods", "retail_ecommerce", "technology_telecoms", "financial_services",
             "automotive_mobility", "healthcare_pharma", "travel_hospitality",
             "media_entertainment_gaming", "energy_utilities", "public_academic_nonprofit"]
INDUSTRY_BY_POINTS = {40: CORE, 30: ADJACENT, 20: CONNECTED, 0: ["other"], None: ["unknown"]}
INDUSTRY_POINTS = {code: pts for pts, codes in INDUSTRY_BY_POINTS.items() for code in codes}
SIZE_BY_POINTS = {0: "1-10", 5: "11-49", 10: "50-249", 15: "250-999", 20: "1000_plus", None: "unknown"}
SIZE_POINTS = {band: pts for pts, band in SIZE_BY_POINTS.items()}
FREQ_BY_POINTS = {25: "monthly_or_more", 15: "recurring_less_than_monthly", 5: "one_off", 0: "none", None: "unknown"}
RELEVANT_USE = ["respondents_fieldwork", "panel_management", "both"]
READY_FIELDS = ["uses_digital_research_tools", "integration_required", "technical_resource_available",
                "adoption_owner_confirmed", "onboarding_support_needed", "adoption_interest_confirmed",
                "adoption_unwilling_or_unable"]
READY_BY_POINTS = {
    15: {"uses_digital_research_tools": True, "integration_required": True, "technical_resource_available": True},
    10: {"uses_digital_research_tools": True},
    5: {"adoption_interest_confirmed": True, "onboarding_support_needed": True},
    0: {"adoption_unwilling_or_unable": True},
    None: {},
}
COMPONENTS = ("industry", "size", "need", "readiness")
COMPLETE_COMBOS = sorted(itertools.product([40, 30, 20, 0], [0, 5, 10, 15, 20], [25, 15, 5, 0], [15, 10, 5, 0]))
REQUEST_TYPES = ["demo_requested", "sales_contact_requested", "quote_requested"]
DOWNLOAD_TYPES = ["guide_downloaded", "case_study_downloaded"]
PRIORITY_CODE = {2: "PRIORITY_EXPLICIT_REQUEST", 3: "PRIORITY_HIGH_FIT_HIGH_ENGAGEMENT",
                 4: "PRIORITY_HIGH_ENGAGEMENT", 5: "PRIORITY_STANDARD_FIT",
                 6: "PRIORITY_MISSING_INFO", 7: "PRIORITY_DEFAULT"}
ALIASES = {"es": "ES", "spain": "ES", "españa": "ES", "espana": "ES", "pt": "PT", "portugal": "PT",
           "fr": "FR", "france": "FR", "de": "DE", "deutschland": "DE", "germany": "DE",
           "it": "IT", "italia": "IT", "italy": "IT", "gb": "GB", "uk": "GB", "united kingdom": "GB"}
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

# ---------------------------------------------------------------------------
# Fictional names (all domains use the reserved .example top-level domain)
# ---------------------------------------------------------------------------
FIRST = {
    "ES": ["Lucía", "Javier", "Marta", "Pablo", "Elena", "Sergio", "Carmen", "Diego", "Laura", "Andrés",
           "Nuria", "Raúl", "Inés", "Álvaro", "Paula", "Iván", "Rocío", "Hugo", "Alba", "Mario"],
    "PT": ["João", "Inês", "Tiago", "Beatriz", "Rui", "Mariana", "Pedro", "Catarina", "Nuno", "Sofia",
           "Miguel", "Leonor", "André", "Rita", "Duarte", "Matilde"],
    "FR": ["Camille", "Louis", "Chloé", "Hugo", "Léa", "Antoine", "Manon", "Julien", "Emma", "Théo",
           "Sarah", "Lucas", "Clara", "Maxime", "Julie", "Nicolas"],
    "DE": ["Jonas", "Lena", "Felix", "Anna"], "IT": ["Giulia", "Marco", "Sara", "Luca"],
    "GB": ["Oliver", "Amelia", "Harry", "Isla"],
}
LAST = {
    "ES": ["García", "Martín", "López", "Sánchez", "Romero", "Navarro", "Torres", "Ruiz", "Moreno",
           "Ortega", "Castillo", "Vidal", "Serrano", "Molina", "Delgado", "Iglesias"],
    "PT": ["Silva", "Santos", "Ferreira", "Pereira", "Costa", "Rodrigues", "Martins", "Sousa", "Almeida",
           "Ribeiro", "Carvalho", "Lopes"],
    "FR": ["Martin", "Bernard", "Dubois", "Moreau", "Laurent", "Simon", "Michel", "Lefèvre", "Leroy",
           "Roux", "Fournier", "Girard"],
    "DE": ["Weber", "Becker", "Wagner"], "IT": ["Rossi", "Bianchi", "Ricci"], "GB": ["Smith", "Taylor", "Walker"],
}
COMPANY_WORDS = {
    "ES": (["Estudios", "Datos", "Panel", "Mercados", "Opinión", "Consultora", "Campo", "Tendencias", "Sondeos", "Análisis"],
           ["Atlas", "Faro", "Brújula", "Prisma", "Vértice", "Delta", "Norte", "Ibérica", "Horizonte", "Sol"]),
    "PT": (["Estudos", "Dados", "Painel", "Mercados", "Opinião", "Consultores", "Campo", "Tendências", "Sondagens", "Análise"],
           ["Atlântico", "Farol", "Bússola", "Prisma", "Vértice", "Delta", "Norte", "Lusa", "Horizonte", "Tejo"]),
    "FR": (["Études", "Données", "Panel", "Marchés", "Opinion", "Conseil", "Terrain", "Tendances", "Sondages", "Analyse"],
           ["Atlas", "Phare", "Boussole", "Prisme", "Sommet", "Delta", "Nord", "Azur", "Horizon", "Seine"]),
    "DE": (["Markt", "Daten", "Umfrage"], ["Nord", "Blick", "Werk"]),
    "IT": (["Ricerche", "Dati", "Sondaggi"], ["Faro", "Vetta", "Delta"]),
    "GB": (["Insight", "Field", "Panel"], ["Harbour", "Summit", "Bridge"]),
}
PERSONAL_DOMAINS = {"ES": "correo-personal.example", "PT": "correio-pessoal.example",
                    "FR": "courriel-perso.example", "DE": "post-privat.example",
                    "IT": "posta-privata.example", "GB": "personal-mail.example"}
COUNTRY_INPUTS = {"ES": ["ES", "Spain", "España", "es", " Spain "], "PT": ["PT", "Portugal", "portugal"],
                  "FR": ["FR", "France", "france"]}
COUNTRY_NAMES = {"ES": "Spain", "PT": "Portugal", "FR": "France"}
UNSUPPORTED_INPUTS = [("Deutschland", "DE"), ("Italia", "IT"), ("United Kingdom", "GB")]

# ---------------------------------------------------------------------------
# Helpers: time and text
# ---------------------------------------------------------------------------
def iso(t):
    return t.astimezone(MAD).isoformat(timespec="seconds")


def parse(ts):
    return datetime.fromisoformat(ts)


def slug(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _work_start(t):
    t = t.astimezone(MAD)
    while True:
        if t.weekday() >= 5 or t.time() >= time(18):
            t = datetime.combine(t.date() + timedelta(days=1), time(9), MAD)
            continue
        if t.time() < time(9):
            return datetime.combine(t.date(), time(9), MAD)
        return t


def add_business_minutes(start, minutes):
    """Monday-Friday 09:00 up to (not including) 18:00, Europe/Madrid."""
    t = _work_start(start)
    left = minutes
    while True:
        end = datetime.combine(t.date(), time(18), MAD)
        available = int((end - t).total_seconds() // 60)
        if left <= available:
            return t + timedelta(minutes=left)
        left -= available
        t = _work_start(end)


def business_minutes_between(a, b):
    a, b = a.astimezone(MAD), b.astimezone(MAD)
    if b <= a:
        return 0
    total, d = 0, a.date()
    while d <= b.date():
        if d.weekday() < 5:
            s = max(a, datetime.combine(d, time(9), MAD))
            e = min(b, datetime.combine(d, time(18), MAD))
            if e > s:
                total += int((e - s).total_seconds() // 60)
        d += timedelta(days=1)
    return total


def rep_active(rep, t):
    for u in UNAVAILABLE:
        if u["rep"] == rep and t >= u["from"] and (u["until"] is None or t < u["until"]):
            return False
    return True


def norm_country(value):
    if value is None or not value.strip():
        return None
    return ALIASES.get(value.strip().lower(), "UNRECOGNISED")


BUSINESS_DAYS = [PERIOD_START + timedelta(days=i) for i in range((PERIOD_END - PERIOD_START).days + 1)
                 if (PERIOD_START + timedelta(days=i)).weekday() < 5]
WEEKEND_DAYS = [PERIOD_START + timedelta(days=i) for i in range((PERIOD_END - PERIOD_START).days + 1)
                if (PERIOD_START + timedelta(days=i)).weekday() >= 5]

# ---------------------------------------------------------------------------
# Reference calculation (used to check recipes; independent of the engine)
# ---------------------------------------------------------------------------
def fit_band(total):
    return "high" if total >= 70 else "medium" if total >= 40 else "low"


def reference_fit(company):
    if company is None:
        comps = dict.fromkeys(COMPONENTS)
    else:
        use, freq = company["research_use_case"], company["research_frequency"]
        if freq == "none":
            need = 0
        elif use in RELEVANT_USE and freq in ("monthly_or_more", "recurring_less_than_monthly", "one_off"):
            need = {"monthly_or_more": 25, "recurring_less_than_monthly": 15, "one_off": 5}[freq]
        else:
            need = None
        c = company
        if c.get("uses_digital_research_tools") and c.get("integration_required") and c.get("technical_resource_available"):
            ready = 15
        elif c.get("uses_digital_research_tools") or c.get("adoption_owner_confirmed"):
            ready = 10
        elif c.get("adoption_interest_confirmed"):
            ready = 5
        elif c.get("adoption_unwilling_or_unable"):
            ready = 0
        else:
            ready = None
        comps = {"industry": INDUSTRY_POINTS.get(company["industry_code"]),
                 "size": SIZE_POINTS.get(company["employee_band_declared"]), "need": need, "readiness": ready}
    total = sum(v for v in comps.values() if v is not None)
    complete = all(v is not None for v in comps.values())
    return {"components": comps, "total": total, "status": "complete" if complete else "incomplete",
            "band": fit_band(total) if complete else None}


def reference_engagement(events, coverage, at):
    hi = at.astimezone(UTC)
    lo = hi - WINDOW
    seen, days = set(), set()
    request, webinars, downloads = False, 0, 0
    for e in events:
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        t = parse(e["occurred_at"])
        if not (lo <= t.astimezone(UTC) <= hi):
            continue
        if e["type"] in REQUEST_TYPES:
            request = True
        elif e["type"] == "pricing_page_visited":
            days.add(t.astimezone(MAD).date())
        elif e["type"] == "webinar_attended":
            webinars += 1
        elif e["type"] in DOWNLOAD_TYPES:
            downloads += 1
    if coverage != "complete":
        return {"total": None, "status": "unknown", "band": "unknown", "explicit_request": request}
    total = min(100, (60 if request else 0) + min(20, 10 * len(days)) + min(15, 15 * webinars) + min(10, 5 * downloads))
    band = "high" if total >= 40 else "medium" if total >= 15 else "low"
    return {"total": total, "status": "complete", "band": band, "explicit_request": request}


def reference_priority(fit, eng, relationship):
    complete = fit["status"] == "complete"
    if eng["explicit_request"]:
        return "P1", 2
    if complete and fit["band"] == "high" and eng["band"] == "high":
        return "P1", 3
    if eng["band"] == "high":
        return "P2", 4
    if complete and (fit["band"] == "high" or (fit["band"] == "medium" and eng["band"] == "medium")):
        return "P2", 5
    if not complete or eng["status"] == "unknown" or relationship == "unknown":
        return "P2", 6
    return "P3", 7


def flag_codes(fit, eng, relationship, company):
    codes = []
    if relationship == "unknown":
        codes.append("RELATIONSHIP_UNKNOWN")
    if fit["status"] == "incomplete":
        codes.append("FIT_INCOMPLETE")
    if eng["status"] == "unknown":
        codes.append("ENGAGEMENT_UNKNOWN")
    if company is not None and company.get("company_domain") is None:
        codes.append("DOMAIN_MISSING")
    return codes


def public_eng(eng):
    return {"total": eng["total"], "status": eng["status"], "band": eng["band"]}

# ---------------------------------------------------------------------------
# Follow-up activity plans (deterministic per lead)
# ---------------------------------------------------------------------------
def plan_activities(email, assigned_at, priority, force=None):
    r = random.Random(f"{SEED}:{email}")
    allowance = TARGET_MINUTES[priority]
    category = force or r.choices(["within_target", "target_missed", "breached"], weights=[62, 26, 12])[0]
    if priority == "P3" and category == "target_missed":
        category = "within_target"
    acts = []
    if r.random() < 0.3:
        acts.append({"type": "email", "automated": True, "at": assigned_at + timedelta(minutes=1)})
    human = "call" if r.random() < 0.6 else "email"
    if category == "within_target":
        acts.append({"type": human, "automated": False, "at": add_business_minutes(assigned_at, r.randint(5, allowance))})
    elif category == "target_missed":
        acts.append({"type": human, "automated": False,
                     "at": add_business_minutes(assigned_at, r.randint(allowance + 5, SLA_MINUTES))})
    elif category == "breached" and r.random() < 0.5:
        acts.append({"type": human, "automated": False, "at": add_business_minutes(assigned_at, r.randint(495, 900))})
    return {"category": category, "activities": acts}


def happened(act, owner):
    return act["at"] <= CUTOFF and rep_active(owner, act["at"])


def first_qualifying(lead):
    if not lead.get("owner") or not lead.get("assigned_at"):
        return None
    times = [a["at"] for a in lead["plan"]["activities"]
             if not a["automated"] and a["at"] >= lead["assigned_at"] and happened(a, lead["owner"])]
    return min(times) if times else None

# ---------------------------------------------------------------------------
# Builder: creates plans (one per inbound event)
# ---------------------------------------------------------------------------
class Builder:
    def __init__(self):
        self.rng = random.Random(SEED)
        self.used_people, self.used_emails, self.used_domains, self.used_names = set(), set(), set(), set()
        self.used_minutes = set()
        self.eng_counter = 0
        self.crm_counter = 3000
        self.plans = []

    # -- identities --------------------------------------------------------
    def person(self, country):
        for _ in range(500):
            first, last = self.rng.choice(FIRST[country]), self.rng.choice(LAST[country])
            if (first, last) not in self.used_people:
                self.used_people.add((first, last))
                return first, last
        raise RuntimeError("ran out of names")

    def company_identity(self, country, with_domain=True):
        prefixes, suffixes = COMPANY_WORDS[country]
        for _ in range(500):
            name = f"{self.rng.choice(prefixes)} {self.rng.choice(suffixes)}"
            if name not in self.used_names:
                break
        else:
            name = f"{name} {len(self.used_names)}"
        self.used_names.add(name)
        if not with_domain:
            return name, None
        domain, n = f"{slug(name)}.example", 2
        while domain in self.used_domains:
            domain, n = f"{slug(name)}-{n}.example", n + 1
        self.used_domains.add(domain)
        return name, domain

    def email_for(self, first, last, domain):
        email = f"{slug(first)}.{slug(last)}@{domain}"
        assert email not in self.used_emails, email
        self.used_emails.add(email)
        return email

    def messy(self, email):
        x = self.rng.random()
        if x < 0.2:
            local, dom = email.split("@")
            return ".".join(p.capitalize() for p in local.split(".")) + "@" + dom.capitalize()
        if x < 0.3:
            return f"  {email} "
        return email

    def crm_id(self):
        self.crm_counter += 1
        return f"CRM-C-{self.crm_counter}"

    # -- company and engagement -------------------------------------------
    def pick_fit(self, kind):
        if kind == "incomplete":
            pts = list(self.rng.choice(COMPLETE_COMBOS))
            for i in self.rng.sample(range(4), self.rng.choice([1, 1, 2])):
                pts[i] = None
            return tuple(pts)
        return self.rng.choice([c for c in COMPLETE_COMBOS if fit_band(sum(c)) == kind])

    def make_company(self, country, points, with_domain=True):
        ind, size, need, ready = points
        name, domain = self.company_identity(country, with_domain)
        company = {"company_name": name, "company_domain": domain,
                   "industry_code": self.rng.choice(INDUSTRY_BY_POINTS[ind]),
                   "employee_band_declared": SIZE_BY_POINTS[size],
                   "research_use_case": self.rng.choice(RELEVANT_USE) if need in (25, 15, 5)
                   else ("other" if need == 0 else "unknown"),
                   "research_frequency": FREQ_BY_POINTS[need]}
        flags = dict.fromkeys(READY_FIELDS)
        flags.update(READY_BY_POINTS[ready])
        company.update(flags)
        got = reference_fit(company)["components"]
        assert tuple(got[c] for c in COMPONENTS) == tuple(points), (points, got)
        return company

    def ev(self, typ, t):
        self.eng_counter += 1
        return {"id": f"ENG-{self.eng_counter:04d}", "type": typ, "occurred_at": iso(t)}

    def before(self, at, lo_min, hi_min):
        return (at.astimezone(UTC) - timedelta(minutes=self.rng.randint(lo_min, hi_min))).astimezone(MAD)

    def on_day(self, at, days_back, hour_lo=8, hour_hi=21):
        d = at.astimezone(MAD).date() - timedelta(days=days_back)
        return datetime.combine(d, time(self.rng.randint(hour_lo, hour_hi), self.rng.randrange(60)), MAD)

    def make_engagement(self, kind, at):
        events, coverage = [], "complete"

        def pricing(n):
            return [self.ev("pricing_page_visited", self.on_day(at, d)) for d in self.rng.sample(range(1, 21), n)]

        def webinar():
            return [self.ev("webinar_attended", self.on_day(at, self.rng.randint(1, 25)))]

        def download():
            return [self.ev(self.rng.choice(DOWNLOAD_TYPES), self.on_day(at, self.rng.randint(1, 25)))]

        if kind == "request":
            events.append(self.ev(self.rng.choice(REQUEST_TYPES), self.before(at, 2, 600)))
            if self.rng.random() < 0.4:
                events += pricing(1)
        elif kind == "high":
            events += pricing(2) + webinar() + download()
            for _ in range(self.rng.choice([0, 1, 2])):
                events += download()
        elif kind == "medium":
            combo = self.rng.choice([["w"], ["p2"], ["w", "d"], ["w", "p1"], ["p2", "d"],
                                     ["w", "p1", "d"], ["p2", "d", "d"], ["w", "p2"]])
            for c in combo:
                events += webinar() if c == "w" else download() if c == "d" else pricing(int(c[1]))
        elif kind == "low":
            combo = self.rng.choice(["none", "d", "dd", "p1", "same_day"])
            if combo == "d":
                events += download()
            elif combo == "dd":
                events += download() + download()
            elif combo == "p1":
                events += pricing(1)
            elif combo == "same_day":
                d = at.astimezone(MAD).date() - timedelta(days=self.rng.randint(1, 15))
                events += [self.ev("pricing_page_visited", datetime.combine(d, time(8, self.rng.randrange(60)), MAD)),
                           self.ev("pricing_page_visited", datetime.combine(d, time(22, self.rng.randrange(60)), MAD))]
        elif kind == "unknown":
            coverage = self.rng.choice(["failed", "partial"])
            if coverage == "partial":
                events += download()
        if coverage == "complete":
            if self.rng.random() < 0.25:
                old = self.rng.choice(["pricing_page_visited", "webinar_attended", "guide_downloaded", "demo_requested"])
                events.append(self.ev(old, self.on_day(at, self.rng.randint(32, 45))))
            if events and self.rng.random() < 0.15:
                events.append(dict(self.rng.choice(events)))
        events.sort(key=lambda e: parse(e["occurred_at"]))
        return events, coverage

    # -- times -------------------------------------------------------------
    def take(self, t):
        if t in self.used_minutes or t > CUTOFF:
            return False
        self.used_minutes.add(t)
        return True

    def sample_time(self, out_of_hours=False, day=None, lo=(9, 0), hi=(17, 45), avoid=None):
        for _ in range(2000):
            if out_of_hours:
                kind = self.rng.choice(["evening", "early", "weekend"])
                if kind == "weekend":
                    d, h = self.rng.choice(WEEKEND_DAYS), self.rng.randint(10, 19)
                elif kind == "evening":
                    d, h = self.rng.choice(BUSINESS_DAYS), self.rng.randint(18, 21)
                else:
                    d, h = self.rng.choice(BUSINESS_DAYS), self.rng.randint(7, 8)
                t = datetime.combine(d, time(h, self.rng.randrange(60)), MAD)
            else:
                d = day or self.rng.choice(BUSINESS_DAYS)
                m = self.rng.randint(lo[0] * 60 + lo[1], hi[0] * 60 + hi[1])
                t = datetime.combine(d, time(m // 60, m % 60), MAD)
            if avoid and avoid(t):
                continue
            if self.take(t):
                return t
        raise RuntimeError("could not find a free time")

    # -- plan construction ----------------------------------------------
    def base_input(self, received, first, last, email, country_input, relationship, company, eng_kind):
        events, coverage = self.make_engagement(eng_kind, received) if eng_kind else ([], "complete")
        inp = {"source_system": SOURCE_SYSTEM, "source_event_id": None, "event_type": "lead_created",
               "source_occurred_at": iso(received - timedelta(minutes=self.rng.randint(1, 3))),
               "email": email, "first_name": first, "last_name": last,
               "business_country": country_input, "relationship_type": relationship,
               "company": company, "engagement_events": events, "engagement_coverage": coverage}
        return inp

    def add(self, group, subtype, received, inp, intent=None, **extra):
        plan = {"key": len(self.plans), "group": group, "subtype": subtype, "received_at": received,
                "input": inp, "intent": intent or {}}
        plan.update(extra)
        self.plans.append(plan)
        return plan

    def lead_plan(self, group, subtype, country, received, fit_kind, eng_kind, relationship="buyer",
                  intended_rule=None, with_domain=True, country_input=_UNSET, name_country=None, **extra):
        name_country = name_country or country
        first, last = self.person(name_country)
        company = self.make_company(name_country, self.pick_fit(fit_kind), with_domain=with_domain)
        domain = company["company_domain"] or PERSONAL_DOMAINS[name_country]
        email = self.email_for(first, last, domain)
        if country_input is _UNSET:
            country_input = self.rng.choice(COUNTRY_INPUTS[country])
        inp = self.base_input(received, first, last, self.messy(email), country_input, relationship, company, eng_kind)
        if self.rng.random() < 0.25:
            inp["crm_contact_id"] = self.crm_id()
        return self.add(group, subtype, received, inp,
                        intent={"fit_kind": fit_kind, "eng_kind": eng_kind, "rule": intended_rule}, **extra)

# ---------------------------------------------------------------------------
# Simulation (applies LF-002 to the plans in processing order)
# ---------------------------------------------------------------------------
def new_state():
    return {"leads": {}, "crm": {}, "company_first": {}, "rotation": dict(INITIAL_ROTATION),
            "processed": {}, "plans_cache": {}}


def rotate(state, country, t):
    reps = REPS[country]
    start = reps.index(state["rotation"][country])
    skipped = []
    for i in range(len(reps)):
        rep = reps[(start + i) % len(reps)]
        if rep_active(rep, t):
            state["rotation"][country] = reps[(start + i + 1) % len(reps)]
            return rep, skipped
        skipped.append(rep)
    return None, skipped


def score(company, events, coverage, relationship, at):
    fit = reference_fit(company)
    eng = reference_engagement(events, coverage, at)
    priority, rule = reference_priority(fit, eng, relationship)
    return fit, eng, priority, rule


def process(state, plan):
    inp, t = plan["input"], plan["received_at"]
    sid = inp.get("source_event_id")
    if sid is None:
        return {"outcome": "rejected", "event_stored": True, "processing_status": "rejected",
                "error_code": "SOURCE_EVENT_INVALID", "lead_created": False, "owner": None,
                "review_queue": "unassigned_review", "action_owner": "revops", "round_robin_advanced": False,
                "fit": None, "engagement": None, "priority": None, "priority_rule": None,
                "reason_codes": ["SOURCE_EVENT_INVALID"], "sla": None, "response_target": None}
    if sid in state["processed"]:
        lead = state["leads"].get(state["processed"][sid])
        return {"outcome": "duplicate_event_ignored", "event_stored_again": False, "new_decision": False,
                "lead_created": False, "owner": lead["owner"] if lead else None, "review_queue": None,
                "round_robin_advanced": False, "reason_codes": ["DUPLICATE_EVENT_RECONTACT"]}
    state["processed"][sid] = None
    country = norm_country(inp.get("business_country"))

    if inp.get("enquiry_type") == "paid_survey_participant":
        rule = REDIRECT_RULES.get(country)
        base = {"normalised_email": None, "country_code": country, "lead_created": False, "owner": None,
                "round_robin_advanced": False, "fit": None, "engagement": None, "priority": None,
                "priority_rule": None, "sla": None, "response_target": None}
        if rule:
            base.update({"outcome": "redirected", "processing_status": "redirected", "review_queue": None,
                         "reason_codes": ["PARTICIPANT_REDIRECT"],
                         "referral": {"referral_method": "automated_reply_panelists", "attempt_status": "simulated",
                                      "supplier_code": rule["supplier_code"], "destination_url": rule["destination_url"],
                                      "personal_data_transferred": False}})
        else:
            base.update({"outcome": "review", "processing_status": "review_required",
                         "review_queue": "participant_redirect_review", "action_owner": "revops",
                         "reason_codes": ["NO_REDIRECT_RULE"],
                         "referral": {"referral_method": "automated_reply_panelists", "attempt_status": "review_required",
                                      "error_code": "NO_REDIRECT_RULE", "personal_data_transferred": False}})
        return base

    email = (inp.get("email") or "").strip().lower()
    relationship = inp["relationship_type"]
    if not EMAIL_RE.fullmatch(email):
        fit, eng, prio, rule = score(inp["company"], inp["engagement_events"], inp["engagement_coverage"], relationship, t)
        return {"outcome": "review", "processing_status": "review_required", "normalised_email": None,
                "country_code": country if country in REPS else None, "lead_created": False, "owner": None,
                "review_queue": "unassigned_review", "action_owner": "revops", "round_robin_advanced": False,
                "fit": fit, "engagement": public_eng(eng), "priority": prio, "priority_rule": rule,
                "reason_codes": ["EMAIL_INVALID", PRIORITY_CODE[rule]] + flag_codes(fit, eng, relationship, inp["company"]),
                "sla": None, "response_target": None, "waiting_since": iso(t)}

    crm = inp.get("crm_contact_id")
    if email in state["leads"]:
        return returning(state, plan, state["leads"][email], email, "email")
    if crm and crm in state["crm"]:
        return returning(state, plan, state["leads"][state["crm"][crm]], email, "crm")
    return new_lead(state, plan, email, country)


def returning(state, plan, lead, event_email, how):
    inp, t = plan["input"], plan["received_at"]
    state["processed"][inp["source_event_id"]] = lead["email"]
    company = inp.get("company") or lead["company"]
    lead["events"] = lead["events"] + inp["engagement_events"]
    fit, eng, prio, rule = score(company, lead["events"], inp["engagement_coverage"], inp["relationship_type"], t)
    since = business_minutes_between(lead["first_contact_at"], t)
    codes = []
    if how == "crm":
        codes.append("IDENTITY_REVIEW")
    elif since < RECONTACT_MINUTES:
        codes.append("DUPLICATE_EVENT_RECONTACT")
    else:
        codes.append("EXISTING_CONTACT")
    owner_inactive = not rep_active(lead["owner"], t)
    if owner_inactive:
        codes.append("OWNER_REVIEW")
    codes.append(PRIORITY_CODE[rule])
    codes += flag_codes(fit, eng, inp["relationship_type"], company)
    fq = first_qualifying(lead)
    followed = fq is not None and fq <= t
    changed = False
    if not followed and PRIORITY_RANK[prio] < PRIORITY_RANK[lead["priority"]]:
        candidate = min(lead["target_at"], add_business_minutes(t, TARGET_MINUTES[prio]))
        if candidate < lead["target_at"]:
            lead["target_changes"].append({"at": iso(t), "from": iso(lead["target_at"]), "to": iso(candidate),
                                           "new_priority": prio})
            lead["target_at"] = candidate
            changed = True
    lead["priority"] = prio
    if how == "crm":
        outcome = "attached_to_existing_contact"
    elif owner_inactive:
        outcome = "review"
    else:
        outcome = "existing_owner_kept"
    result = {"outcome": outcome, "lead_created": False, "normalised_email": event_email,
              "country_code": lead["country"], "owner": lead["owner"],
              "review_queue": "unassigned_review" if owner_inactive else None,
              "action_owner": "sales_manager" if owner_inactive else None,
              "round_robin_advanced": False, "fit": fit, "engagement": public_eng(eng),
              "priority": prio, "priority_rule": rule, "reason_codes": codes,
              "sla": {"new_sla_created": False, "deadline": iso(lead["sla_deadline"]),
                      "followed_up_before_event": followed},
              "response_target": None if followed else
              {"priority": prio, "target_at": iso(lead["target_at"]), "target_changed": changed}}
    if how == "crm":
        result["stored_email_kept"] = lead["email"]
        result["parallel_review"] = {"reason_code": "IDENTITY_REVIEW", "action_owner": "revops"}
    return result


def new_lead(state, plan, email, country):
    inp, t = plan["input"], plan["received_at"]
    state["processed"][inp["source_event_id"]] = email
    relationship = inp["relationship_type"]
    company = inp["company"]
    domain = company.get("company_domain") if company else None
    fit, eng, prio, rule = score(company, inp["engagement_events"], inp["engagement_coverage"], relationship, t)
    crm_country = inp.get("crm_business_country")
    conflict = crm_country is not None and norm_country(crm_country) != country
    lead = {"email": email, "country": None, "owner": None, "assigned_at": None, "first_contact_at": t,
            "company": company, "events": list(inp["engagement_events"]), "priority": prio,
            "sla_deadline": None, "target_at": None, "target_changes": [], "plan": None,
            "first_seq_key": plan["key"], "relationship": relationship}
    state["leads"][email] = lead
    if inp.get("crm_contact_id"):
        state["crm"][inp["crm_contact_id"]] = email
    lead_codes = []
    supplier_side = relationship in ("supplier", "both")
    exception, action_owner, skipped, owner, outcome = None, None, [], None, None
    colleague = None
    if domain and domain in state["company_first"]:
        first = state["company_first"][domain]
        if business_minutes_between(first["at"], t) < RECONTACT_MINUTES:
            colleague = state["leads"][first["email"]]
    if domain and domain not in state["company_first"]:
        state["company_first"][domain] = {"at": t, "email": email}

    if conflict:
        exception, action_owner = "COUNTRY_CONFLICT", "revops"
    elif country is None or country == "UNRECOGNISED":
        exception, action_owner = "COUNTRY_INVALID", "revops"
    elif country not in REPS:
        exception, action_owner = "UNSUPPORTED_TERRITORY", "sales_manager"
        lead["country"] = country
    else:
        lead["country"] = country
        if colleague and colleague["owner"] and rep_active(colleague["owner"], t):
            owner, outcome = colleague["owner"], "assigned_to_company_owner"
            lead_codes.append("SAME_COMPANY_RECENT_CONTACT")
        else:
            owner, skipped = rotate(state, country, t)
            if owner is None:
                exception, action_owner = "NO_ELIGIBLE_OWNER", "sales_manager"
            else:
                outcome = "assigned"
    codes = ([exception] if exception else []) + lead_codes + (["SUPPLIER_REVIEW"] if supplier_side else [])
    codes += [PRIORITY_CODE[rule]] + flag_codes(fit, eng, relationship, company)
    result = {"normalised_email": email, "country_code": lead["country"], "lead_created": True,
              "fit": fit, "engagement": public_eng(eng), "priority": prio, "priority_rule": rule,
              "reason_codes": codes}
    if supplier_side:
        result["parallel_review"] = {"reason_code": "SUPPLIER_REVIEW", "action_owner": "sales_manager"}
    if exception:
        result.update({"outcome": "review", "owner": None, "review_queue": "unassigned_review",
                       "action_owner": action_owner, "round_robin_advanced": False,
                       "round_robin_next_after": state["rotation"].get(lead["country"]) if lead["country"] in REPS else None,
                       "sla": None, "response_target": None, "waiting_since": iso(t)})
        return result
    lead.update({"owner": owner, "assigned_at": t, "sla_deadline": add_business_minutes(t, SLA_MINUTES),
                 "target_at": add_business_minutes(t, TARGET_MINUTES[prio])})
    lead["initial_target_at"] = lead["target_at"]
    lead["initial_priority"] = prio
    cache = state["plans_cache"]
    if email not in cache:
        cache[email] = plan_activities(email, t, prio, plan.get("force_followup"))
    lead["plan"] = cache[email]
    result.update({"outcome": outcome, "owner": owner, "review_queue": None,
                   "round_robin_advanced": outcome == "assigned", "round_robin_next_after": state["rotation"][country],
                   "sla": {"starts": iso(t), "allowance_business_minutes": SLA_MINUTES,
                           "deadline": iso(lead["sla_deadline"])},
                   "response_target": {"priority": prio, "allowance_business_minutes": TARGET_MINUTES[prio],
                                       "target_at": iso(lead["target_at"])}})
    if skipped:
        result["rotation_skipped"] = skipped
    return result


def simulate(plans, plans_cache=None):
    state = new_state()
    if plans_cache is not None:
        state["plans_cache"] = plans_cache
    results = {}
    for plan in sorted(plans, key=lambda p: (p["received_at"], p["key"])):
        results[plan["key"]] = process(state, plan)
    return state, results

# ---------------------------------------------------------------------------
# Dataset construction
# ---------------------------------------------------------------------------
ASSIGNABLE_RULES = ["R2"] * 8 + ["R3"] * 4 + ["R4"] * 6 + ["R5"] * 10 + ["R6"] * 9 + ["R7"] * 18
RULE_NUMBER = {"R2": 2, "R3": 3, "R4": 4, "R5": 5, "R6": 6, "R7": 7}


def recipe(rng, rule):
    if rule == "R2":
        return rng.choice(["high", "medium", "low", "incomplete"]), "request"
    if rule == "R3":
        return "high", "high"
    if rule == "R4":
        return rng.choice(["medium", "low", "incomplete"]), "high"
    if rule == "R5":
        return rng.choice([("high", "low"), ("high", "medium"), ("high", "unknown"), ("medium", "medium")])
    if rule == "R6":
        return rng.choice([("incomplete", "low"), ("incomplete", "medium"), ("incomplete", "unknown"),
                           ("medium", "unknown"), ("low", "unknown")])
    return rng.choice([("medium", "low"), ("low", "low"), ("low", "medium")])


def pt_offsite(t):
    return t.date() == date(2026, 10, 21)


def build_base(b):
    rng = b.rng
    # 1. New buyer leads that should be assigned (55)
    countries = ["ES"] * 18 + ["PT"] * 17 + ["FR"] * 18
    rng.shuffle(countries)
    countries = ["ES", "ES"] + countries
    rules = list(ASSIGNABLE_RULES)
    rng.shuffle(rules)
    no_domain = set(rng.sample(range(8, 55), 3))
    out_of_hours = set(rng.sample(range(8, 55), 8))
    for i in range(55):
        country, rule = countries[i], rules[i]
        force, avoid = None, (pt_offsite if country == "PT" else None)
        if i in (0, 1):
            received = b.sample_time(day=date(2026, 10, 28))
        elif 2 <= i <= 5:
            received = b.sample_time(day=date(2026, 11, 6), lo=(11, 0), hi=(17, 30))
            force = "pending"
        elif i == 6:
            received = b.sample_time(day=date(2026, 10, 23), lo=(16, 0), hi=(16, 59), avoid=avoid)
        elif i == 7:
            received = b.sample_time(day=rng.choice([date(2026, 10, 24), date(2026, 10, 25)]), lo=(10, 0), hi=(19, 0))
        else:
            received = b.sample_time(out_of_hours=i in out_of_hours, avoid=avoid)
        fit_kind, eng_kind = recipe(rng, rule)
        b.lead_plan("new_buyer_assignable", "assignable", country, received, fit_kind, eng_kind,
                    intended_rule=RULE_NUMBER[rule], with_domain=i not in no_domain, force_followup=force)
    # 2. Supplier-only (4) and buyer-and-supplier (3)
    for i in range(7):
        country = rng.choice(["ES", "PT", "FR"])
        received = b.sample_time(avoid=pt_offsite if country == "PT" else None)
        if i < 4:
            first, last = b.person(country)
            pts = (40, rng.choice([5, 10, 15]), None, None)
            company = b.make_company(country, pts)
            company["industry_code"] = rng.choice(["panel_sample_provider", "market_research"])
            company["research_use_case"] = "other"
            email = b.email_for(first, last, company["company_domain"])
            inp = b.base_input(received, first, last, b.messy(email), rng.choice(COUNTRY_INPUTS[country]),
                               "supplier", company, "low")
            inp["enquiry_text"] = "We run a respondent panel and would like to supply participants."
            b.add("supplier_or_both", "supplier", received, inp, intent={"rule": 6})
        else:
            fit_kind, eng_kind = rng.choice([("high", "low"), ("high", "medium"), ("medium", "request")])
            p = b.lead_plan("supplier_or_both", "both", country, received, fit_kind, eng_kind, relationship="both",
                            intended_rule=2 if eng_kind == "request" else 5)
            p["input"]["enquiry_text"] = "We want your fieldwork platform and could also supply our own panel."
    # 3. Relationship unknown (3)
    for fit_kind, eng_kind in [("low", "low"), ("medium", "low"), ("low", "medium")]:
        country = rng.choice(["ES", "PT", "FR"])
        received = b.sample_time(avoid=pt_offsite if country == "PT" else None)
        b.lead_plan("relationship_unknown", "relationship_unknown", country, received, fit_kind, eng_kind,
                    relationship="unknown", intended_rule=6)
    # 4. Blocking exceptions on new events (9 + 2 invalid emails; owner review is added later)
    any_recipe = lambda: recipe(rng, rng.choice(ASSIGNABLE_RULES))
    for country_input in [None, "", "  "]:
        f, e = any_recipe()
        b.lead_plan("blocking_exception", "missing_country", rng.choice(["ES", "PT", "FR"]),
                    b.sample_time(), f, e, country_input=country_input)
    for a, c in [("ES", "PT"), ("FR", "ES")]:
        f, e = any_recipe()
        p = b.lead_plan("blocking_exception", "country_conflict", a, b.sample_time(), f, e)
        p["input"]["crm_business_country"] = COUNTRY_NAMES[c]
    for text, code in UNSUPPORTED_INPUTS:
        f, e = any_recipe()
        b.lead_plan("blocking_exception", "unsupported_territory", code, b.sample_time(), f, e,
                    country_input=text, name_country=code)
    f, e = any_recipe()
    b.lead_plan("blocking_exception", "no_eligible_owner", "PT", b.sample_time(day=date(2026, 10, 21)), f, e)
    for form in ["(at)", "missing_domain"]:
        country = rng.choice(["ES", "FR"])
        f, e = any_recipe()
        p = b.lead_plan("blocking_exception", "invalid_email", country, b.sample_time(), f, e)
        good = p["input"]["email"].strip().lower()
        local, dom = good.split("@")
        p["input"]["email"] = f"{local}(at){dom}" if form == "(at)" else f"{local}@"
    # 5. Paid-survey participants (5; PT has no redirect rule)
    for country in ["ES", "FR", "ES", "FR", "PT"]:
        first, last = b.person(country)
        received = b.sample_time()
        inp = b.base_input(received, first, last, b.email_for(first, last, PERSONAL_DOMAINS[country]),
                           rng.choice(COUNTRY_INPUTS[country]), "unknown", None, None)
        inp["enquiry_type"] = "paid_survey_participant"
        inp["enquiry_text"] = {"ES": "¿Cómo puedo participar en encuestas pagadas?",
                               "FR": "Comment participer à des sondages rémunérés ?",
                               "PT": "Quero participar em inquéritos pagos."}[country]
        b.add("participant", "participant" if country in REDIRECT_RULES else "participant_no_rule", received, inp)
    # 6. Malformed events (3): no source event ID
    for _ in range(3):
        country = rng.choice(["ES", "PT", "FR"])
        f, e = any_recipe()
        b.lead_plan("malformed", "malformed", country, b.sample_time(avoid=pt_offsite if country == "PT" else None),
                    f, e, malformed=True)


def build_dependents(b, base_state):
    rng = b.rng
    leads = base_state["leads"]
    by_key = {p["key"]: p for p in b.plans}
    pool = sorted([l for l in leads.values() if l["owner"] and by_key[l["first_seq_key"]]["group"] == "new_buyer_assignable"],
                  key=lambda l: l["first_seq_key"])
    used = set()

    def pick(pred):
        cands = [l for l in pool if l["email"] not in used and pred(l)]
        if not cands:
            raise RuntimeError("no candidate lead for dependent event")
        lead = rng.choice(cands)
        used.add(lead["email"])
        return lead

    def single_event(typ, t):
        return [b.ev(typ, b.before(t, 2, 120))]

    def follow_input(lead, t, events, with_company=True, email=None):
        src = by_key[lead["first_seq_key"]]["input"]
        inp = {"source_system": SOURCE_SYSTEM, "source_event_id": None, "event_type": "lead_updated",
               "source_occurred_at": iso(t - timedelta(minutes=2)), "email": email or b.messy(lead["email"]),
               "first_name": src["first_name"], "last_name": src["last_name"],
               "business_country": src["business_country"], "relationship_type": src["relationship_type"],
               "company": copy.deepcopy(src["company"]) if with_company else None,
               "engagement_events": events, "engagement_coverage": "complete"}
        if src.get("crm_contact_id"):
            inp["crm_contact_id"] = src["crm_contact_id"]
        return inp

    def later_time(lead, after, min_days, last_day=PERIOD_END):
        days = [d for d in BUSINESS_DAYS if after.date() + timedelta(days=min_days) <= d <= last_day]
        rng.shuffle(days)
        for d in days:
            for _ in range(20):
                t = datetime.combine(d, time(rng.randint(9, 17), rng.randrange(60)), MAD)
                if t > after and rep_active(lead["owner"], t) and b.take(t):
                    return t
        return None

    def within_time(lead, lo, hi):
        for _ in range(200):
            t = add_business_minutes(lead["first_contact_at"], rng.randint(lo, hi))
            if rep_active(lead["owner"], t) and b.take(t):
                return t
        return None

    # Existing contacts, 8+ business hours later and already followed up (4)
    for subtype in ["existing_after_followup_request", "existing_stored_company", "existing", "existing"]:
        while True:
            lead = pick(lambda l: first_qualifying(l) is not None)
            t = later_time(lead, first_qualifying(lead) + timedelta(minutes=30), 2)
            if t:
                break
        typ = rng.choice(REQUEST_TYPES) if subtype == "existing_after_followup_request" else \
            rng.choice(["pricing_page_visited", "guide_downloaded"])
        inp = follow_input(lead, t, single_event(typ, t), with_company=subtype != "existing_stored_company")
        b.add("returning_contact", subtype, t, inp)
    # Recontacts within 8 business hours (4; the first upgrades priority before follow-up)
    for subtype in ["recontact_upgrade", "recontact", "recontact", "recontact"]:
        while True:
            if subtype == "recontact_upgrade":
                lead = pick(lambda l: l["priority"] in ("P2", "P3"))
            else:
                lead = pick(lambda l: True)
            t = within_time(lead, 45, 420)
            if t is None:
                continue
            if subtype == "recontact_upgrade":
                fq = first_qualifying(lead)
                if fq is not None and fq <= t:
                    b.used_minutes.discard(t)
                    continue
            break
        typ = rng.choice(REQUEST_TYPES) if subtype == "recontact_upgrade" else \
            rng.choice(["pricing_page_visited", "guide_downloaded", "webinar_attended"])
        b.add("returning_contact", subtype, t, follow_input(lead, t, single_event(typ, t)))
    # Colleagues from the same company within 8 business hours (2)
    for _ in range(2):
        while True:
            lead = pick(lambda l: l["company"] and l["company"].get("company_domain"))
            t = within_time(lead, 60, 400)
            if t:
                break
        src = by_key[lead["first_seq_key"]]["input"]
        country = lead["country"]
        first, last = b.person(country)
        email = b.email_for(first, last, lead["company"]["company_domain"])
        inp = b.base_input(t, first, last, b.messy(email), src["business_country"], "buyer",
                           copy.deepcopy(lead["company"]), rng.choice(["low", "medium"]))
        b.add("returning_contact", "same_company", t, inp)
    # Ambiguous identity: new email but an existing CRM contact ID (2)
    for _ in range(2):
        while True:
            lead = pick(lambda l: by_key[l["first_seq_key"]]["input"].get("crm_contact_id")
                        and l["company"] and l["company"].get("company_domain"))
            t = later_time(lead, lead["first_contact_at"], 2)
            if t:
                break
        src = by_key[lead["first_seq_key"]]["input"]
        new_email = f"{slug(src['first_name'])[0]}.{slug(src['last_name'])}@{lead['company']['company_domain']}"
        inp = follow_input(lead, t, single_event("pricing_page_visited", t), email=new_email)
        inp["event_type"] = "lead_created"
        b.add("ambiguous_identity", "ambiguous_identity", t, inp)
    # Existing owner has become inactive (1): an FR-02 lead returns after 2 November
    lead = pick(lambda l: l["owner"] == "FR-02" and l["assigned_at"] < _mad(2026, 11, 2))
    t = later_time({"owner": "FR-01"}, _mad(2026, 11, 3), 0)
    b.add("blocking_exception", "owner_review", t, follow_input(lead, t, single_event("pricing_page_visited", t)))
    # Replays of earlier events (3)
    for _ in range(3):
        lead = pick(lambda l: True)
        original = by_key[lead["first_seq_key"]]
        for _ in range(200):
            t = original["received_at"] + timedelta(minutes=rng.randint(5, 90))
            if b.take(t):
                break
        b.add("replay", "replay", t, None, replay_of=original["key"])


def assign_ids(plans):
    by_key = {p["key"]: p for p in plans}
    n = 0
    for p in sorted(plans, key=lambda p: (p["received_at"], p["key"])):
        if p.get("replay_of") is not None:
            p["input"] = copy.deepcopy(by_key[p["replay_of"]]["input"])
        elif p.get("malformed"):
            p["input"]["source_event_id"] = None
        else:
            n += 1
            p["input"]["source_event_id"] = f"SYN-L{n:03d}"


PATTERNS = {"malformed": "S-14", "replay": "S-17", "participant": "S-09", "participant_no_rule": "S-29",
            "invalid_email": "S-24", "missing_country": "S-12", "country_conflict": "S-23",
            "unsupported_territory": "S-13", "no_eligible_owner": "S-25", "owner_review": "S-26",
            "ambiguous_identity": "S-11", "same_company": "S-22", "recontact": "S-21",
            "recontact_upgrade": "S-15", "existing": "S-10", "existing_after_followup_request": "S-32",
            "existing_stored_company": "S-10", "supplier": "S-08", "both": "S-30",
            "relationship_unknown": "S-28"}
RULE_PATTERNS = {2: "S-01", 3: "S-02", 4: "S-03", 6: "S-05", 7: "S-07"}

# Every event type must show the reason code it was designed to test.
SUBTYPE_CODE = {"missing_country": "COUNTRY_INVALID", "country_conflict": "COUNTRY_CONFLICT",
                "unsupported_territory": "UNSUPPORTED_TERRITORY", "no_eligible_owner": "NO_ELIGIBLE_OWNER",
                "invalid_email": "EMAIL_INVALID", "owner_review": "OWNER_REVIEW",
                "ambiguous_identity": "IDENTITY_REVIEW", "same_company": "SAME_COMPANY_RECENT_CONTACT",
                "recontact": "DUPLICATE_EVENT_RECONTACT", "recontact_upgrade": "DUPLICATE_EVENT_RECONTACT",
                "existing": "EXISTING_CONTACT", "existing_stored_company": "EXISTING_CONTACT",
                "existing_after_followup_request": "EXISTING_CONTACT", "supplier": "SUPPLIER_REVIEW",
                "both": "SUPPLIER_REVIEW", "participant": "PARTICIPANT_REDIRECT",
                "participant_no_rule": "NO_REDIRECT_RULE", "replay": "DUPLICATE_EVENT_RECONTACT",
                "malformed": "SOURCE_EVENT_INVALID", "relationship_unknown": "RELATIONSHIP_UNKNOWN"}


def patterns_for(plan, exp):
    pats = []
    if plan["subtype"] in PATTERNS:
        pats.append(PATTERNS[plan["subtype"]])
    elif exp.get("priority_rule") == 5:
        pats.append("S-04" if exp["fit"]["band"] == "high" else "B-04")
    elif exp.get("priority_rule") == 6 and exp["engagement"]["status"] == "unknown" and exp["fit"]["status"] == "complete":
        pats.append("S-06")
    elif exp.get("priority_rule") in RULE_PATTERNS:
        pats.append(RULE_PATTERNS[exp["priority_rule"]])
    codes = exp.get("reason_codes", [])
    if exp.get("rotation_skipped"):
        pats.append("S-31")
    if "DOMAIN_MISSING" in codes:
        pats.append("S-27")
    events = (plan["input"] or {}).get("engagement_events") or []
    pricing_days = Counter(parse(e["occurred_at"]).astimezone(MAD).date() for e in events
                           if e["type"] == "pricing_page_visited")
    if any(n > 1 for n in pricing_days.values()):
        pats.append("S-20")
    return pats


def fmt(ts):
    return parse(ts).strftime("%a %d %b %H:%M") if ts else "-"


def explain(plan, exp):
    o = exp["outcome"]
    if o == "rejected":
        return "No source event ID: stored for traceability, rejected with SOURCE_EVENT_INVALID."
    if o == "duplicate_event_ignored":
        return "Same source event delivered again: ignored, nothing changes."
    if o == "redirected":
        return f"Paid-survey participant: simulated referral to {exp['referral']['supplier_code']}; no lead, score or SLA."
    if plan["subtype"] == "participant_no_rule":
        return "Paid-survey participant from a country without a redirect rule: RevOps handles it; no lead."
    fit, eng = exp["fit"], exp["engagement"]
    fit_txt = f"fit {fit['band']} ({fit['total']})" if fit["status"] == "complete" else f"fit incomplete (provisional {fit['total']})"
    eng_txt = f"engagement {eng['band']} ({eng['total']})" if eng["status"] == "complete" else "engagement unknown"
    head = f"{fit_txt}, {eng_txt} -> {exp['priority']} (rule {exp['priority_rule']})"
    if o in ("assigned", "assigned_to_company_owner"):
        how = "colleague's owner" if o == "assigned_to_company_owner" else "round-robin"
        skip = f", skipped {', '.join(exp['rotation_skipped'])}" if exp.get("rotation_skipped") else ""
        return (f"{head}; {how} -> {exp['owner']}{skip}; target {fmt(exp['response_target']['target_at'])}, "
                f"SLA {fmt(exp['sla']['deadline'])}.")
    if o == "review" and exp.get("action_owner") and exp.get("owner") is None:
        return f"{head} shown while waiting; {exp['reason_codes'][0]} -> unassigned_review ({exp['action_owner']}); no SLA yet."
    kind = {"existing_owner_kept": "returning contact", "attached_to_existing_contact": "matched by CRM contact ID",
            "review": "owner inactive -> Sales Manager review"}[o]
    tgt = exp["response_target"]
    if tgt is None:
        return f"{kind}; {head}; owner {exp['owner']}; already followed up, so no new SLA or target."
    change = " (target shortened)" if tgt["target_changed"] else ""
    return f"{kind}; {head}; owner {exp['owner']}; no new SLA, target {fmt(tgt['target_at'])}{change}."


def lead_outcomes(state):
    rows = []
    for lead in sorted(state["leads"].values(), key=lambda l: l["first_seq_key"]):
        row = {"lead_email": lead["email"], "country_code": lead["country"], "owner": lead["owner"],
               "status": "assigned" if lead["owner"] else "waiting_in_review"}
        if lead["owner"]:
            fq = first_qualifying(lead)
            deadline, target = lead["sla_deadline"], lead["target_at"]
            if fq is not None and fq <= deadline:
                sla = "met"
            elif fq is not None or CUTOFF > deadline:
                sla = "breached"
            else:
                sla = "pending"
            if fq is not None and fq <= target:
                tgt = "met"
            elif fq is not None or CUTOFF > target:
                tgt = "missed"
            else:
                tgt = "pending"
            row.update({"assigned_at": iso(lead["assigned_at"]), "initial_priority": lead["initial_priority"],
                        "final_priority": lead["priority"], "sla_deadline": iso(deadline),
                        "response_target_at": iso(target), "target_changes": lead["target_changes"],
                        "first_qualifying_followup_at": iso(fq) if fq else None,
                        "sla_outcome": sla, "response_target_outcome": tgt})
        rows.append(row)
    return rows


def activities(state):
    acts = []
    for lead in state["leads"].values():
        if not lead["owner"]:
            continue
        for a in lead["plan"]["activities"]:
            if a["at"] >= lead["assigned_at"] and happened(a, lead["owner"]):
                acts.append({"lead_email": lead["email"], "owner": lead["owner"], "type": a["type"],
                             "automated": a["automated"], "occurred_at": a["at"]})
    acts.sort(key=lambda a: (a["occurred_at"], a["lead_email"]))
    for i, a in enumerate(acts, 1):
        a["occurred_at"] = iso(a["occurred_at"])
        acts[i - 1] = {"activity_id": f"ACT-{i:04d}", "source_system": "synthetic_crm", **a}
    return acts


# Where each enquiry came from (LF-011 source mix). Drawn from its own random stream per
# event, so adding it changes no other generated value. A replay repeats its original.
CHANNEL_WEIGHTS = [("web_form", 45), ("event", 20), ("partner", 10), ("referral", 10),
                   ("outbound", 10), ("unknown", 5)]


def assign_channels(plans):
    by_key = {p["key"]: p for p in plans}
    names = [c for c, _ in CHANNEL_WEIGHTS]
    weights = [w for _, w in CHANNEL_WEIGHTS]
    for p in sorted(plans, key=lambda p: p.get("replay_of") is not None):
        if p.get("replay_of") is not None:
            p["input"]["source_channel"] = by_key[p["replay_of"]]["input"]["source_channel"]
        else:
            ident = p["input"].get("source_event_id") or f"key-{p['key']}"
            p["input"]["source_channel"] = random.Random(f"{SEED}:channel:{ident}").choices(names, weights)[0]


def build():
    b = Builder()
    build_base(b)
    for p in b.plans:
        p["input"]["source_event_id"] = f"TMP-{p['key']}" if not p.get("malformed") else None
    base_state, base_results = simulate(b.plans)
    build_dependents(b, base_state)
    assign_ids(b.plans)
    assign_channels(b.plans)
    state, results = simulate(b.plans, plans_cache=base_state["plans_cache"])
    for key, r in base_results.items():
        assert results[key].get("owner") == r.get("owner"), ("base owner changed", key)

    ordered = sorted(b.plans, key=lambda p: (p["received_at"], p["key"]))
    events, expected = [], []
    for seq, plan in enumerate(ordered, 1):
        exp = results[plan["key"]]
        intended = plan["intent"].get("rule")
        if intended is not None:
            assert exp["priority_rule"] == intended, (plan["subtype"], intended, exp["priority_rule"])
        if plan["intent"].get("fit_kind") in ("high", "medium", "low") and exp.get("fit"):
            assert exp["fit"]["band"] == plan["intent"]["fit_kind"], (plan["key"], exp["fit"])
        if plan["intent"].get("eng_kind") in ("high", "medium", "low", "unknown") and exp.get("engagement"):
            assert exp["engagement"]["band"] == plan["intent"]["eng_kind"], (plan["key"], exp["engagement"])
        code = SUBTYPE_CODE.get(plan["subtype"])
        assert code is None or code in exp["reason_codes"], (plan["subtype"], exp["reason_codes"])
        if plan["subtype"] in ("assignable", "relationship_unknown", "supplier", "both"):
            assert exp["outcome"] == "assigned", (plan["subtype"], exp["outcome"])
        if plan["subtype"] == "recontact_upgrade":
            assert exp["response_target"]["target_changed"] and exp["priority"] == "P1"
        if plan["subtype"] == "existing_after_followup_request":
            assert exp["sla"]["followed_up_before_event"] and exp["priority"] == "P1"
            assert exp["response_target"] is None
        events.append({"seq": seq, "received_at": iso(plan["received_at"]), "input": plan["input"]})
        expected.append({"seq": seq, "source_event_id": plan["input"]["source_event_id"],
                         "received_at": iso(plan["received_at"]), "group": plan["group"],
                         "subtype": plan["subtype"], "patterns": patterns_for(plan, exp),
                         "expected": exp, "explanation": explain(plan, exp)})
    groups = Counter(p["group"] for p in b.plans)
    assert dict(groups) == GROUP_TARGETS, groups
    assert len(events) == 100

    leads = lead_outcomes(state)
    acts = activities(state)
    summary = {
        "events": len(events),
        "events_by_group": dict(sorted(groups.items())),
        "events_by_outcome": dict(sorted(Counter(e["expected"]["outcome"] for e in expected).items())),
        "leads_created": sum(1 for e in expected if e["expected"].get("lead_created")),
        "leads_assigned": sum(1 for l in leads if l["owner"]),
        "leads_waiting_in_review": sum(1 for l in leads if not l["owner"]),
        "sla_outcomes_at_cutoff": dict(sorted(Counter(l["sla_outcome"] for l in leads if l["owner"]).items())),
        "response_target_outcomes_at_cutoff": dict(sorted(Counter(l["response_target_outcome"] for l in leads if l["owner"]).items())),
        "priority_rules": dict(sorted(Counter(str(e["expected"].get("priority_rule")) for e in expected
                                              if e["expected"].get("priority_rule")).items())),
        "followup_activities": len(acts),
    }
    metadata = {
        "description": "Synthetic inbound enquiry events for MoP Cloud (LF-005). All data is fictional.",
        "rule_version": RULE_VERSION, "seed": SEED, "generated_by": "tools/generate_synthetic_leads.py",
        "timezone": "Europe/Madrid", "period": {"start": PERIOD_START.isoformat(), "end": PERIOD_END.isoformat()},
        "processing": "Events are processed in seq order, each at its received_at time.",
        "sla_cutoff": iso(CUTOFF),
        "representatives": REPS, "initial_rotation": INITIAL_ROTATION,
        "unavailability": [{"rep": u["rep"], "from": iso(u["from"]), "until": iso(u["until"]) if u["until"] else None,
                            "reason": u["reason"]} for u in UNAVAILABLE],
        "supplier_redirect_rules": REDIRECT_RULES,
    }
    data = {"metadata": metadata, "events": events, "followup_activities": acts}
    exp_doc = {"metadata": {"rule_version": RULE_VERSION, "sla_cutoff": iso(CUTOFF),
                            "notes": ["Expected outcomes are designed outcome-first from LF-002 and traceable to LF-004 patterns.",
                                      "The order of reason_codes is not significant; compare them as sets.",
                                      "Event-level expectations describe the state when each event is processed; "
                                      "lead-level outcomes are evaluated at sla_cutoff."]},
               "summary": summary, "events": expected, "leads": leads}
    files = {DATA_FILE: json.dumps(data, indent=2, ensure_ascii=False) + "\n",
             EXPECTED_FILE: json.dumps(exp_doc, indent=2, ensure_ascii=False) + "\n",
             DOC_FILE: render_doc(summary, expected, leads, events)}
    return files

# ---------------------------------------------------------------------------
# Documentation page
# ---------------------------------------------------------------------------
def render_doc(summary, expected, leads, events):
    def table(counter, head):
        rows = [f"| {k} | {v} |" for k, v in counter.items()]
        return "\n".join([f"| {head} | Count |", "|---|---:|"] + rows)

    def seqs(pred):
        found = [str(e["seq"]) for e in expected if pred(e)]
        return ", ".join(found) if found else "-"

    edge = [
        ("Rotation skipped an inactive representative", seqs(lambda e: e["expected"].get("rotation_skipped"))),
        ("Arrived outside working hours or at a weekend", seqs(lambda e: (lambda t: t.weekday() >= 5 or not time(9) <= t.time() < time(18))(parse(e["received_at"])))),
        ("SLA deadline crosses the 25 Oct clock change", seqs(lambda e: (e["expected"].get("sla") or {}).get("starts", "9999") < "2026-10-25" and (e["expected"].get("sla") or {}).get("deadline", "0") > "2026-10-25")),
        ("Pending at the cut-off (assigned 6 Nov)", seqs(lambda e: e["received_at"].startswith("2026-11-06") and e["expected"].get("outcome") == "assigned")),
        ("Two pricing visits on the same Madrid day", seqs(lambda e: "S-20" in e["patterns"])),
        ("Missing company domain", seqs(lambda e: "DOMAIN_MISSING" in e["expected"].get("reason_codes", []))),
        ("Response target shortened by a priority increase", seqs(lambda e: (e["expected"].get("response_target") or {}).get("target_changed"))),
        ("Returning contact already followed up (no new SLA or target)", seqs(lambda e: (e["expected"].get("sla") or {}).get("followed_up_before_event"))),
        ("Existing contact without company data (stored data used)", seqs(lambda e: e["subtype"] == "existing_stored_company")),
    ]
    assigned = [l for l in leads if l["owner"]]
    met_missed = sum(1 for l in assigned if l["sla_outcome"] == "met" and l["response_target_outcome"] == "missed")
    lines = [
        "# LF-005 Synthetic dataset",
        "",
        "Generated by `tools/generate_synthetic_leads.py`. Do not edit by hand: change the generator and rerun it.",
        "",
        "## What it is",
        "",
        "100 fictional inbound enquiry events for MoP Cloud between Monday 12 October and Friday 6 November 2026 "
        "(Europe/Madrid), with follow-up activities and the expected outcome of every event under "
        f"`{RULE_VERSION}`. All names use invented people and companies; every domain ends in `.example`.",
        "",
        "## Files",
        "",
        "| File | Content |",
        "|---|---|",
        f"| `{DATA_FILE}` | Settings (reps, availability, redirect rules, cut-off), the 100 events in processing order, follow-up activities |",
        f"| `{EXPECTED_FILE}` | Expected outcome per event (with LF-004 pattern references and an explanation), lead-level SLA outcomes at the cut-off, summary counts |",
        f"| `{DOC_FILE}` | This page |",
        "",
        "## How to regenerate and check",
        "",
        "```bash",
        "python3 tools/generate_synthetic_leads.py          # rewrite the files",
        "python3 tools/generate_synthetic_leads.py --check  # fail if they are out of date",
        "python3 -m pytest                                  # validation tests",
        "```",
        "",
        f"The random seed is fixed (`{SEED}`), so the files are identical on every run.",
        "",
        "## How expected outcomes are produced",
        "",
        "- **Outcome first.** Each new lead comes from a recipe that states its intended result (for example "
        "high fit + low engagement -> P2, rule 5); the inputs are built to match.",
        "- **Checked.** A small reference calculation inside the generator confirms every recipe and works out "
        "returning contacts. It shares no code with the routing engine (LF-006/LF-007).",
        "- **Traceable.** Every event lists the reviewed LF-004 scenario(s) it follows.",
        "- **Primary reference.** The hand-reviewed LF-004 scenarios remain the acceptance tests; this dataset adds volume.",
        "",
        "## Settings",
        "",
        "- Starting rotation: ES-01, PT-01, FR-01 (representative-ID order).",
        "- Unavailability: PT-01 and PT-02 on 21 Oct (offsite), ES-01 on 28 Oct (day off), FR-02 from 2 Nov (left the team).",
        "- Supplier redirect rules exist for ES and FR only.",
        f"- SLA and response-target outcomes are evaluated at {fmt(iso(CUTOFF))} (the cut-off).",
        "- Inactive representatives keep their existing leads but log no activity while inactive.",
        "",
        "## Mix",
        "",
        table(summary["events_by_group"], "Group"),
        "",
        table(summary["events_by_outcome"], "Expected outcome"),
        "",
        f"Leads created: **{summary['leads_created']}** (assigned {summary['leads_assigned']}, "
        f"waiting in review {summary['leads_waiting_in_review']}). The rest of the 100 events are returning contacts, "
        "participants, replays, invalid emails and malformed events.",
        "",
        table(summary["priority_rules"], "Priority rule"),
        "",
        table(dict(Counter(e["input"]["source_channel"] for e in events).most_common()), "Source channel"),
        "",
        "Source channels (added in LF-011 for reporting) come from a separate random stream, so they changed "
        "no other value. They do not affect routing.",
        "",
        "## SLA and response targets at the cut-off",
        "",
        table(summary["sla_outcomes_at_cutoff"], "SLA outcome"),
        "",
        table(summary["response_target_outcomes_at_cutoff"], "Response-target outcome"),
        "",
        f"SLA met but response target missed: **{met_missed}** leads. Follow-up activities: {summary['followup_activities']} "
        "(automated emails are included and must not count as qualifying follow-up).",
        "",
        "## Edge cases (event seq numbers)",
        "",
        "| Edge case | Events |",
        "|---|---|",
    ] + [f"| {name} | {s} |" for name, s in edge] + [
        "",
        "## Limitations",
        "",
        "- Expected outcomes come from the generator's own reference calculation, checked against the recipes. "
        "A stratified random sample of 20 was checked by hand: 20 of 20 agreed (`docs/synthetic_dataset_review.md`).",
        "- Public holidays are not modelled (as in the MVP).",
        "- Data is synthetic. No real people, companies or personal data are used.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed files are out of date")
    args = parser.parse_args()
    files = build()
    stale = []
    for rel, content in files.items():
        path = ROOT / rel
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(rel)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"wrote {rel}")
    if args.check:
        if stale:
            print("out of date: " + ", ".join(stale))
            sys.exit(1)
        print("dataset files are up to date")


if __name__ == "__main__":
    main()
