# Advoxy Real Estate Marketplace: Spec and Claude Code Build Prompt

Working name: **Advoxy** (placeholder; brand, name, and logo are swapped in at the end, so keep all branding in one config file).

---

## 1. Decisions locked

- Scope: pan-African, no country-specific rules. Use general data protection practices (consent, data export, deletion, minimal data collection).
- Languages: English only. Structure all UI text for translation (Django i18n), but do not translate yet.
- Currency: USD by default, set in one config value (`CURRENCY_CODE`, `CURRENCY_SYMBOL`). No multi-currency in phase 1.
- Payments: **Stripe** only. Payments cover paid listings, featured placement, and agent/agency subscriptions. No payments for property sales or rentals (handled off-platform).
- Hosting: Hostinger VPS.
- Stack: Django full stack, Django templates, HTMX, Alpine.js, Tailwind CSS, PostgreSQL + PostGIS, Celery + Redis, Mapbox for maps.
- Messaging: in-app, phase 1. Implemented with HTMX polling every 5 seconds in v1. Channels/WebSockets is a later upgrade.
- Demo: a live demo URL on the VPS with seeded data for every role, plus a recorded walkthrough.

**Known risk (must be decided before launch):** Stripe does not support merchant accounts in most African countries. It works for some (for example South Africa, Kenya, Nigeria, Ghana, Egypt, and others, subject to Stripe's current list). A universal African gateway needs a second provider (for example Flutterwave or Paystack) for the countries Stripe does not cover. This spec builds a payment adapter so a second provider plugs in without rewriting the app. Stripe is wired first.

---

## 2. Roles and accounts

One user account model with roles. A user can hold more than one capability.

| Role | Can do |
|---|---|
| Buyer | Browse, search, save, save searches, send inquiries, message agents/owners |
| Renter | Same as buyer, filtered to rentals |
| Individual owner / seller / landlord | All buyer features, plus list properties. Free tier: 2 active listings for landlords, 1 for sellers. Extra listings and featured placement are paid |
| Agent | All buyer features, plus list properties under an agency-agnostic profile. Requires an active subscription. Verified badge after admin review |
| Agency | Multiple agent seats, agency profile, team listings. Tiered subscription. Verified badge after admin review |
| Admin | Full internal dashboard (see section 6). Separate staff login |

Rules:
- Sign up, log in, password reset, email verification.
- Verification upload for agents and agencies (license document). Admin approves or rejects.
- Each role has its own dashboard home screen.

---

## 3. Listings

Property types: apartment, villa, townhouse, land, commercial. Phase 1 builds residential (apartment, villa, townhouse). Land and commercial are **included as types in the data model** but may use the residential form. Confirm before adding dedicated fields.

Listing purpose: sale or rent.

Fields: title, description, type, purpose, price (in USD), bedrooms, bathrooms, area (m²), furnished (yes/no), amenities (multi-select), address text, city, country, neighborhood, map pin (latitude/longitude, draggable), photos (multiple, reordered, first photo is the cover), status, featured flag, created/updated dates.

Listing lifecycle: draft → pending review → published → (expired | sold/rented | removed). Admin moderation queue gates publishing.

Listing limits enforced in code:
- Landlord: 2 free active listings. Seller: 1 free active listing. Additional: paid.
- Agent and agency: plan-based capacity.
- Featured placement: paid, time-limited.

---

## 4. Search and map (Bayut-style)

- Split view: map on one side, result cards on the other. Mobile: toggle between list and map.
- Filters: location (city, neighborhood, map area), purpose (buy/rent), type, price range, bedrooms, bathrooms, area, furnished, amenities, sort (newest, price, featured first).
- Map: Mapbox GL. Pins with price bubbles. Clicking a pin opens a preview card.
- Location search uses PostGIS for "within radius" and "inside drawn area".
- Saved searches with email alerts (daily digest).
- Favorites (save listings).
- Listing detail page: photo gallery, price, key facts, map, description, amenities, agent/owner card, inquiry form, similar listings.

---

## 5. Inquiries and messaging

- Inquiry form on every listing: name, email, phone (optional), message. Sends an email to the listing owner/agent and creates a message thread.
- In-app messaging: threads between a user and a listing owner/agent, tied to a listing. Unread counts. Polling every 5s via HTMX. Email notification for new messages (throttled).

---

## 6. Admin dashboard (must be excellent)

This is a core deliverable. It must be easy to manage and easy to read.

- Overview home: key metrics (total listings, pending reviews, active users by role, revenue this month, new inquiries), with charts and a recent-activity feed.
- Moderation queue: pending listings with preview, approve, reject with reason, request edits.
- Users: search, filter by role, view profile, suspend, verify agent/agency, change role.
- Verifications: queue of uploaded license documents, approve or reject.
- Listings: full table with filters, bulk actions (feature, unpublish, delete with confirmation).
- Payments and subscriptions: Stripe records, subscription status, paid listing and featured placement purchases, refunds through Stripe dashboard link.
- Settings: currency, site name, logo, featured pricing, listing limits, subscription tiers. All editable without code.
- Audit log: who changed what and when.

Design: clean data tables with sticky headers, status badges, keyboard-friendly filters, dark and light mode, responsive down to tablet.

---

## 7. Public site design

- Premium, calm, editorial. Large photography, restrained palette, strong typography, generous whitespace.
- No generic template look. Custom components, not default Tailwind UI blocks.
- Pages: home (hero search, featured listings, areas), search, listing detail, agents directory, agency profile, pricing (listings and subscriptions), about, contact, help, login/signup, role dashboards.
- Accessibility: WCAG AA contrast, keyboard navigation, alt text on photos.
- Brand config: name, logo, colors, fonts are in one config file and one CSS theme file so the client rebrand happens in one place.

---

## 8. Payments (Stripe)

- Stripe Checkout for one-time purchases (extra listing, featured placement) and Stripe Billing for subscriptions (agent, agency tiers).
- Stripe webhooks update the database. Verify webhook signatures.
- Payment adapter interface: `create_checkout(...)`, `handle_webhook(...)`, `cancel_subscription(...)`. Stripe is the only implementation in phase 1.
- All amounts in USD via `CURRENCY_CODE` config.
- No property sale or rental payments.

---

## 9. Data model (core)

- User (custom, with role flags), Profile, AgencyTeam, AgentProfile, VerificationDocument
- Listing, ListingPhoto, Amenity, ListingLocation (PostGIS point)
- SavedSearch, Favorite
- Inquiry, Thread, Message, MessageRead
- Plan, Subscription, Purchase (one-time), FeaturedPlacement
- Setting (key/value for admin-editable config)
- AuditLog

---

## 10. Email

- Transactional emails via SMTP (configurable). Celery sends them.
- Templates: verify email, reset password, new inquiry, new message, listing approved/rejected, verification approved/rejected, subscription receipts, saved-search digest.

---

## 11. Demo and seed data (required)

- `python manage.py seed_demo` creates:
  - 60+ listings across at least 8 African cities (for example Nairobi, Lagos, Accra, Cape Town, Kigali, Addis Ababa, Cairo, Kampala). Use realistic prices in USD, placeholder photos, real coordinates.
  - Demo accounts: buyer, renter, individual seller, landlord, agent, agency with 3 agents, admin. All with known passwords documented in `DEMO.md`.
  - Sample inquiries and message threads.
- A demo banner on the live demo site only (controlled by an env flag).
- `DEMO.md`: how to log in as each role and what to try.

---

## 12. Deployment (Hostinger VPS)

- Ubuntu VPS. Nginx reverse proxy, Gunicorn, PostgreSQL 16 with PostGIS, Redis, Celery worker and beat under systemd.
- HTTPS via Let's Encrypt.
- Environment variables in `.env` on the server only, never committed.
- Deploy script: `deploy/deploy.sh` (pull, install, migrate, collectstatic, restart).
- Backups: nightly PostgreSQL dump.

---

## 13. Milestones (build in this order, demo at each)

Each milestone must end with a working, testable demo and a checked box in `PROGRESS.md`.

1. **Foundation**: project setup, custom user with roles, auth flows, base layout, design system, brand config, PostGIS, seed command.
2. **Listings core**: create, edit, photos, listing limits, detail page, owner dashboard.
3. **Search and map**: filters, Mapbox split view, PostGIS radius search, favorites, saved searches.
4. **Inquiries and messaging**: inquiry form, threads, polling messages, email notifications.
5. **Admin core**: overview, moderation queue, users, verifications, listings table.
6. **Payments**: Stripe checkout for paid listings and featured placement, subscriptions for agents and agencies, webhooks, billing pages.
7. **Agencies and agents**: agency teams, agent directory, verified badges, agency profiles.
8. **Polish and launch**: admin settings page, audit log, email templates, accessibility pass, performance pass, deploy to VPS, recorded walkthrough.

---

## 14. Claude Code build prompt (paste this into Claude Code)

```
You are building a production-quality pan-African real estate marketplace called "Advoxy" (placeholder brand). Read the full spec in SPEC.md before you start. Follow it exactly. Do not add features that are not in the spec. If something is unclear or missing, stop and write the question into QUESTIONS.md, then continue with the parts that are not blocked.

Stack: Python 3.12, Django 5.x, PostgreSQL 16 with PostGIS, Django templates, HTMX, Alpine.js, Tailwind CSS, Celery with Redis, Mapbox GL JS, Stripe.

Rules:
1. Create PROGRESS.md first. List every milestone and every task from SPEC.md section 13 as a checklist item. Add a percentage at the top: completed items divided by total items, rounded down. Update the file after every completed task, in the same step. Never mark a task done until it works and you have tested it.
2. Work in milestone order. Finish one milestone fully (working, tested, seeded demo working) before starting the next.
3. After each milestone, report: milestone name, percentage complete, what works, what is stubbed (if anything), and how to try it.
4. Keep all text in English, wrapped in i18n functions. Keep currency in one setting (CURRENCY_CODE, CURRENCY_SYMBOL). Keep brand name, logo, colors, and fonts in one config file and one theme file.
5. Never commit secrets. Use .env.example with placeholders. Stripe keys, database URL, and Mapbox token come from environment variables.
6. Payments: implement the adapter interface from SPEC.md section 8. Stripe is the only provider. Do not add property sale or rental payments.
7. Messaging uses HTMX polling every 5 seconds in phase 1.
8. Write tests for: role permissions, listing limits, moderation transitions, Stripe webhook signature verification, inquiry creation, and PostGIS radius search. Run them before marking a milestone done.
9. Admin dashboard must be high quality: clear metrics, sortable and filterable tables, status badges, bulk actions with confirmation, dark and light mode, responsive to tablet.
10. Public UI must not look like a default template. Follow the design direction in SPEC.md section 7.
11. Deliver a seed command, DEMO.md, deploy/deploy.sh, and a README with local setup.

Start now with milestone 1.
```

---

## 15. Open items to confirm (short list)

- Stripe only in phase 1 (confirmed). Stripe does not cover most African countries, so a second provider is needed before launch to the countries it doesn't support. The adapter in section 8 makes that addition self-contained.
- Land and commercial: residential only in phase 1 (confirmed).
