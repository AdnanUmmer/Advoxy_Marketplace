from decimal import Decimal

from django.db import migrations

PLANS = [
    # code, name, audience, price, listings, seats, description, order
    ("agent", "Agent", "agent", "29.00", 15, 1, "For independent agents: 15 active listings and a verified profile.", 1),
    ("agency-starter", "Agency Starter", "agency", "99.00", 50, 3, "Up to 3 agents and 50 active listings across the team.", 1),
    ("agency-pro", "Agency Pro", "agency", "249.00", 200, 10, "Up to 10 agents and 200 active listings across the team.", 2),
]


def create_plans(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for code, name, audience, price, listings, seats, desc, order in PLANS:
        Plan.objects.update_or_create(code=code, defaults={
            "name": name, "audience": audience, "price_monthly": Decimal(price), "listing_limit": listings,
            "seats": seats, "description": desc, "sort_order": order, "is_active": True,
        })


def remove_plans(apps, schema_editor):
    apps.get_model("billing", "Plan").objects.filter(code__in=[p[0] for p in PLANS]).delete()


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]
    operations = [migrations.RunPython(create_plans, remove_plans)]
