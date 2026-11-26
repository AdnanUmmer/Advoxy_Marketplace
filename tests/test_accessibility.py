"""Accessibility regression checks on server-rendered HTML (milestone 8).

Not a replacement for a browser audit, but it catches the common slips: missing page language,
images without alt, form fields without a label, unnamed buttons, missing <main>, more than one h1.
"""

from html.parser import HTMLParser

import pytest
from django.urls import reverse

from apps.accounts.models import AgencyTeam, AgentProfile

pytestmark = pytest.mark.django_db
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Audit(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems, self.labels_for, self.fields, self.h1 = [], set(), [], 0
        self.lang = False
        self.has_main = False
        self.stack = []          # open elements: (tag, attrs)
        self.button = None       # [attrs, text]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html" and a.get("lang"):
            self.lang = True
        if tag == "main":
            self.has_main = True
        if tag == "h1":
            self.h1 += 1
        if tag == "img" and "alt" not in a:
            self.problems.append(f"img without alt: {a.get('src')}")
        if tag == "label" and a.get("for"):
            self.labels_for.add(a["for"])
        if tag in ("input", "select", "textarea") and a.get("type") not in ("hidden", "submit", "button"):
            inside_label = any(t == "label" for t, _ in self.stack)
            if not (inside_label or a.get("aria-label") or a.get("aria-labelledby") or a.get("title")):
                self.fields.append(a)
        if tag == "button":
            self.button = [a, ""]
        if tag == "svg" and self.button is not None:
            self.button[1] += "svg"  # icon-only button: still needs aria-label, checked below
        if tag not in VOID:
            self.stack.append((tag, a))

    def handle_endtag(self, tag):
        if tag == "button" and self.button is not None:
            a, text = self.button
            text = text.replace("svg", "").strip()
            if not (text or a.get("aria-label") or a.get(":aria-label") or a.get("title") or a.get("x-text")):
                self.problems.append(f"button without a name: {a}")
            self.button = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.button is not None:
            self.button[1] += data

    def report(self):
        problems = list(self.problems)
        for a in self.fields:
            if a.get("id") not in self.labels_for:
                problems.append(f"field without a label: {a.get('name')}")
        if not self.lang:
            problems.append("no lang on <html>")
        if not self.has_main:
            problems.append("no <main>")
        if self.h1 != 1:
            problems.append(f"{self.h1} h1 elements")
        return problems


def audit(client, url):
    resp = client.get(url)
    assert resp.status_code == 200, url
    parser = Audit()
    parser.feed(resp.content.decode())
    return parser.report()


@pytest.fixture
def world(make_user, make_listing):
    owner = make_user(email="owner@example.com", is_agency=True)
    agency = AgencyTeam.objects.create(owner=owner, name="Acme Homes")
    agent = make_user(email="agent@example.com", is_agent=True)
    AgentProfile.objects.create(user=agent, agency=agency)
    listing = make_listing(agent, agency=agency)
    return {"listing": listing, "agent": agent, "agency": agency}


PUBLIC = ["core:home", "search:results", "agencies:agents", "agencies:agencies", "billing:pricing",
          "core:about", "core:help", "accounts:login", "accounts:signup", "accounts:password_reset"]


@pytest.mark.parametrize("name", PUBLIC)
def test_public_pages(client, world, name):
    assert audit(client, reverse(name)) == []


def test_detail_pages(client, world):
    for url in (world["listing"].get_absolute_url(), reverse("agencies:agent", args=[world["agent"].pk]),
                reverse("agencies:agency", args=[world["agency"].slug])):
        assert audit(client, url) == [], url


STAFF = ["staff:overview", "staff:moderation", "staff:listings", "staff:users", "staff:payments",
         "staff:verifications", "staff:audit", "staff:settings", "staff:emails"]


@pytest.mark.parametrize("name", STAFF)
def test_staff_pages(client, make_user, world, name):
    client.force_login(make_user(is_staff=True))
    assert audit(client, reverse(name)) == []


def test_signed_in_pages(client, world):
    client.force_login(world["agent"])
    for name in ("accounts:dashboard", "accounts:profile", "messaging:inbox", "search:favorites", "search:saved",
                 "listings:create", "billing:account"):
        assert audit(client, reverse(name)) == [], name
