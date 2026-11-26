"""
python manage.py seed_demo [--reset]

Creates demo accounts for every role and 77 listings across 11 cities in 9 priority countries with
real coordinates, realistic USD prices and generated placeholder photos.
Later milestones extend this command (inquiries, threads, subscriptions).
"""

import random
import shutil
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import AgencyTeam, AgentProfile, Profile, User, VerificationStatus
from apps.core import placeholder
from apps.listings.geo import make_point
from apps.listings.models import Amenity, Listing, ListingLocation, ListingPhoto, ListingStatus
from apps.search import filters as search_filters
from apps.search.models import Favorite, SavedSearch

DEMO_DOMAIN = "demo.example.com"
DEMO_PASSWORD = "AdvoxyDemo2026!"

ACCOUNTS = [
    # key, email local part, full name, role flags, extra
    ("admin", "admin", "Amara Okafor", {"is_staff": True, "is_superuser": True}),
    ("buyer", "buyer", "Kwame Mensah", {"is_buyer": True}),
    ("renter", "renter", "Zanele Dlamini", {"is_renter": True}),
    ("seller", "seller", "Tunde Bakare", {"is_seller": True, "is_buyer": True}),
    ("landlord", "landlord", "Wanjiru Kamau", {"is_landlord": True}),
    ("agent", "agent", "Yusuf Hassan", {"is_agent": True}),
    ("agency", "agency", "Nadia El-Sayed", {"is_agency": True}),
    ("agency_agent1", "agency.agent1", "Chidi Eze", {"is_agent": True}),
    ("agency_agent2", "agency.agent2", "Aisha Mohammed", {"is_agent": True}),
    ("agency_agent3", "agency.agent3", "Jean-Paul Habimana", {"is_agent": True}),
]

# city, country, price multiplier, [(neighborhood, lat, lng)]
CITIES = [
    ("Lagos", "Nigeria", 1.25, [("Ikoyi", 6.4520, 3.4350), ("Victoria Island", 6.4281, 3.4219), ("Lekki Phase 1", 6.4478, 3.4723), ("Yaba", 6.5095, 3.3711)]),
    ("Abuja", "Nigeria", 1.1, [("Maitama", 9.0820, 7.4950), ("Asokoro", 9.0430, 7.5260), ("Wuse II", 9.0790, 7.4700), ("Gwarinpa", 9.1100, 7.4030)]),
    ("Nairobi", "Kenya", 1.0, [("Westlands", -1.2676, 36.8108), ("Kilimani", -1.2921, 36.7856), ("Karen", -1.3197, 36.7073), ("Lavington", -1.2786, 36.7700)]),
    ("Johannesburg", "South Africa", 1.1, [("Sandton", -26.1076, 28.0567), ("Rosebank", -26.1452, 28.0436), ("Melrose", -26.1350, 28.0640), ("Bryanston", -26.0550, 28.0230)]),
    ("Cape Town", "South Africa", 1.35, [("Sea Point", -33.9180, 18.3870), ("Camps Bay", -33.9510, 18.3780), ("Gardens", -33.9350, 18.4110), ("Constantia", -34.0270, 18.4450)]),
    ("Accra", "Ghana", 1.05, [("East Legon", 5.6350, -0.1610), ("Airport Residential", 5.6030, -0.1780), ("Cantonments", 5.5786, -0.1736), ("Osu", 5.5560, -0.1820)]),
    ("Addis Ababa", "Ethiopia", 0.75, [("Bole", 8.9960, 38.7890), ("Kazanchis", 9.0160, 38.7690), ("Old Airport", 8.9880, 38.7380), ("CMC", 9.0220, 38.8380)]),
    ("Dakar", "Senegal", 1.0, [("Almadies", 14.7450, -17.5130), ("Plateau", 14.6680, -17.4380), ("Mermoz", 14.7090, -17.4760), ("Ngor", 14.7470, -17.5150)]),
    ("Kinshasa", "DR Congo", 0.8, [("Gombe", -4.3050, 15.3050), ("Ngaliema", -4.3550, 15.2500), ("Limete", -4.3600, 15.3400), ("Ma Campagne", -4.3500, 15.2700)]),
    ("Mogadishu", "Somalia", 0.6, [("Hodan", 2.0370, 45.3070), ("Wadajir", 2.0130, 45.2950), ("Hamarweyne", 2.0350, 45.3450), ("Waberi", 2.0270, 45.3200)]),
    ("Khartoum", "Sudan", 0.55, [("Riyadh", 15.5700, 32.5700), ("Amarat", 15.5800, 32.5450), ("Khartoum 2", 15.5850, 32.5350), ("Manshiya", 15.5950, 32.5800)]),
]
LISTINGS_PER_CITY = 7

AMENITIES = [
    "Swimming pool", "Gym", "Parking", "Garden", "Balcony", "24-hour security", "Backup generator",
    "Borehole water", "Air conditioning", "Elevator", "Sea view", "Staff quarters", "Pet friendly", "Fibre internet",
]

# (min, max) in USD. Sale = total price; rent = per month.
PRICE_BANDS = {
    ("apartment", "sale"): (85_000, 520_000),
    ("villa", "sale"): (320_000, 2_400_000),
    ("townhouse", "sale"): (160_000, 880_000),
    ("apartment", "rent"): (450, 3_800),
    ("villa", "rent"): (1_800, 9_500),
    ("townhouse", "rent"): (1_000, 4_800),
}

ADJECTIVES = ["Light-filled", "Quiet", "Garden", "Contemporary", "Elegant", "Airy", "Renovated", "Spacious", "Corner", "Hillside"]
NOUNS = {"apartment": "apartment", "villa": "villa", "townhouse": "townhouse"}

DESCRIPTION = (
    "A {adj} {kind} in {hood}, {city}, set on a calm street close to schools, shops and cafés.\n\n"
    "The living spaces open to generous natural light, with a kitchen designed for everyday cooking and "
    "entertaining. {beds_text} {baths_text}\n\n"
    "Viewings by appointment. Contact the {lister} through the form on this page."
)


class Command(BaseCommand):
    help = "Seed demo accounts and listings for every role."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing demo data first.")

    def handle(self, *args, **opts):
        demo_users = User.objects.filter(email__endswith=f"@{DEMO_DOMAIN}")
        if demo_users.exists():
            if not opts["reset"]:
                raise CommandError("Demo data already exists. Run with --reset to recreate it.")
            demo_users.delete()  # cascades to listings, profiles, agencies
        self.rnd = random.Random(2026)
        with transaction.atomic():
            self.photo_pool = self._build_photo_pool()
            amenities = self._amenities()
            users = self._accounts()
            count = self._listings(users, amenities)
            self._shortlists(users)
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(ACCOUNTS)} demo accounts and {count} listings."))
        self.stdout.write(f"Password for every demo account: {DEMO_PASSWORD}")

    # ------------------------------------------------------------------
    def _build_photo_pool(self):
        """Photos shared by demo listings, stored under MEDIA_ROOT/seed/.

        Uses the real photos in seed_assets/photos/ (Unsplash License, see CREDITS.md).
        Falls back to generated placeholder drawings if that folder is missing.
        """
        assets = Path(settings.BASE_DIR) / "seed_assets" / "photos"
        real = sorted(assets.glob("*.jpg")) if assets.is_dir() else []
        if real:
            out_dir = Path(settings.MEDIA_ROOT) / "seed"
            out_dir.mkdir(parents=True, exist_ok=True)
            pool = {"apartment": [], "villa": [], "townhouse": [], "interior": []}
            for src in real:
                kind = src.stem.split("-")[0]
                if kind not in pool:
                    continue
                dest = out_dir / src.name
                if not dest.exists() or dest.stat().st_size != src.stat().st_size:
                    shutil.copyfile(src, dest)
                pool[kind].append(f"seed/{src.name}")
            if all(pool.values()):
                return pool
        return self._generated_photo_pool()

    def _generated_photo_pool(self):
        """Generate a reusable pool of placeholder images under MEDIA_ROOT/seed/."""
        out_dir = Path(settings.MEDIA_ROOT) / "seed"
        out_dir.mkdir(parents=True, exist_ok=True)
        pool = {"apartment": [], "villa": [], "townhouse": [], "interior": []}
        for p_idx, palette in enumerate(placeholder.PALETTES):
            for kind in ("apartment", "villa", "townhouse"):
                name = f"seed/{kind}-{p_idx}.jpg"
                path = Path(settings.MEDIA_ROOT) / name
                if not path.exists():
                    path.write_bytes(placeholder.to_jpeg_bytes(placeholder.exterior(kind, palette, seed=p_idx * 7)))
                pool[kind].append(name)
            name = f"seed/interior-{p_idx}.jpg"
            path = Path(settings.MEDIA_ROOT) / name
            if not path.exists():
                path.write_bytes(placeholder.to_jpeg_bytes(placeholder.interior(palette, seed=p_idx)))
            pool["interior"].append(name)
        return pool

    def _amenities(self):
        return [Amenity.objects.get_or_create(slug=slugify(n), defaults={"name": n})[0] for n in AMENITIES]

    def _accounts(self):
        now = timezone.now()
        users = {}
        for key, local, name, flags in ACCOUNTS:
            user = User.objects.create_user(
                email=f"{local}@{DEMO_DOMAIN}", password=DEMO_PASSWORD, full_name=name,
                email_verified_at=now, terms_accepted_at=now, **flags,
            )
            Profile.objects.create(user=user, city="Nairobi", country="Kenya", phone="+254 700 000 000")
            users[key] = user

        agency = AgencyTeam.objects.create(
            owner=users["agency"], name="Meridian Homes", city="Nairobi", country="Kenya",
            description="A pan-African agency with offices in Lagos, Nairobi and Johannesburg.",
            verification_status=VerificationStatus.VERIFIED,
        )
        AgentProfile.objects.create(user=users["agent"], license_number="EARB-2291", years_experience=8,
                                    verification_status=VerificationStatus.VERIFIED)
        statuses = [VerificationStatus.VERIFIED, VerificationStatus.VERIFIED, VerificationStatus.PENDING]
        for i, status in enumerate(statuses, start=1):
            AgentProfile.objects.create(user=users[f"agency_agent{i}"], agency=agency, license_number=f"MH-{100 + i}",
                                        years_experience=3 + i, verification_status=status)
        users["_agency"] = agency
        return users

    def _listings(self, users, amenities):
        rnd = self.rnd
        now = timezone.now()
        agency = users["_agency"]
        pro_owners = ["agent", "agency_agent1", "agency_agent2", "agency_agent3"]
        # Individual owners within their free limits (seller 1, landlord 2), plus one draft each.
        fixed = {
            ("Nairobi", 0): ("seller", "sale", ListingStatus.PUBLISHED),
            ("Lagos", 0): ("seller", "sale", ListingStatus.DRAFT),
            ("Nairobi", 1): ("landlord", "rent", ListingStatus.PUBLISHED),
            ("Accra", 0): ("landlord", "rent", ListingStatus.PUBLISHED),
            ("Dakar", 0): ("landlord", "rent", ListingStatus.DRAFT),
        }
        created = 0
        for city, country, mult, hoods in CITIES:
            for i in range(LISTINGS_PER_CITY):
                owner_key, purpose, status = fixed.get((city, i), (None, None, ListingStatus.PUBLISHED))
                if owner_key is None:
                    owner_key = pro_owners[(created + i) % len(pro_owners)]
                    purpose = "sale" if rnd.random() < 0.55 else "rent"
                    if rnd.random() < 0.08:
                        status = ListingStatus.PENDING
                owner = users[owner_key]
                kind = rnd.choice(["apartment", "apartment", "villa", "townhouse"])
                hood, lat, lng = hoods[i % len(hoods)]
                low, high = PRICE_BANDS[(kind, purpose)]
                raw = rnd.uniform(low, high) * mult
                step = 5_000 if purpose == "sale" else 50
                price = Decimal(int(raw // step * step))
                beds = {"apartment": rnd.randint(1, 3), "villa": rnd.randint(3, 6), "townhouse": rnd.randint(2, 4)}[kind]
                baths = max(1, beds - rnd.randint(0, 1))
                area = {"apartment": rnd.randint(55, 180), "villa": rnd.randint(240, 650), "townhouse": rnd.randint(140, 280)}[kind]
                adj = rnd.choice(ADJECTIVES)
                title = f"{adj} {beds}-bed {NOUNS[kind]} in {hood}"
                is_agency = owner_key.startswith("agency_agent")
                published_at = now - timedelta(days=rnd.randint(1, 60)) if status == ListingStatus.PUBLISHED else None
                listing = Listing.objects.create(
                    owner=owner,
                    agency=agency if is_agency else None,
                    title=title,
                    description=DESCRIPTION.format(
                        adj=adj.lower(), kind=NOUNS[kind], hood=hood, city=city,
                        beds_text=f"There are {beds} bedrooms",
                        baths_text=f"and {baths} bathrooms across {area} m².",
                        lister="agent" if owner.is_agent else "owner",
                    ),
                    property_type=kind,
                    purpose=purpose,
                    price=price,
                    bedrooms=beds,
                    bathrooms=baths,
                    area_sqm=area,
                    furnished=purpose == "rent" and rnd.random() < 0.6,
                    address=f"{rnd.randint(2, 180)} {hood} Road",
                    city=city,
                    country=country,
                    neighborhood=hood,
                    status=status,
                    is_featured=status == ListingStatus.PUBLISHED and owner.is_agent and rnd.random() < 0.18,
                    published_at=published_at,
                    expires_at=published_at + timedelta(days=90) if published_at else None,
                )
                listing.amenities.set(rnd.sample(amenities, rnd.randint(3, 7)))
                # ~1.5 km jitter around the neighborhood centre
                ListingLocation.objects.create(
                    listing=listing,
                    point=make_point(lat + rnd.uniform(-0.012, 0.012), lng + rnd.uniform(-0.012, 0.012)),
                )
                exteriors = rnd.sample(self.photo_pool[kind], min(2, len(self.photo_pool[kind])))
                interiors = rnd.sample(self.photo_pool["interior"], min(3, len(self.photo_pool["interior"])))
                photos = [exteriors[0], *interiors[:2], *exteriors[1:], *interiors[2:]]
                for pos, name in enumerate(photos):
                    photo = ListingPhoto(listing=listing, position=pos, alt_text=f"{title}, photo {pos + 1}")
                    photo.image.name = name
                    photo.save()
                created += 1
        return created

    def _shortlists(self, users):
        """Favorites and saved searches for the buyer and renter demo accounts."""
        published = Listing.objects.published()
        for key, purpose, city, query in (
            ("buyer", "sale", "Nairobi", "purpose=sale&city=Nairobi"),
            ("renter", "rent", "Lagos", "purpose=rent&city=Lagos&beds=2"),
        ):
            user = users[key]
            for listing in published.filter(purpose=purpose).order_by("pk")[:4]:
                Favorite.objects.create(user=user, listing=listing)
            form, _qs, _c = search_filters.search(query)
            SavedSearch.objects.create(user=user, name=search_filters.describe(form), query=search_filters.clean_querystring(query),
                                       last_notified_at=timezone.now())
