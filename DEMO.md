# Demo guide

Create the demo data with `python manage.py seed_demo` (or `--reset` to recreate it). Every demo account uses the same password:

**Password: `AdvoxyDemo2026!`**

| Role | Email | Notes |
|---|---|---|
| Admin (staff) | `admin@demo.example.com` | Sign in at `/accounts/staff/login/` |
| Buyer | `buyer@demo.example.com` | |
| Renter | `renter@demo.example.com` | Home search defaults to rentals |
| Individual seller | `seller@demo.example.com` | Also a buyer. 1 published listing + 1 draft |
| Landlord | `landlord@demo.example.com` | 2 published rentals + 1 draft |
| Independent agent | `agent@demo.example.com` | Verified |
| Agency owner | `agency@demo.example.com` | Meridian Homes (verified) |
| Agency agent 1 | `agency.agent1@demo.example.com` | Verified |
| Agency agent 2 | `agency.agent2@demo.example.com` | Verified |
| Agency agent 3 | `agency.agent3@demo.example.com` | Verification pending |

The seed creates 64 listings across Nairobi, Lagos, Accra, Cape Town, Kigali, Addis Ababa, Cairo and Kampala. Coordinates are real (jittered about 1.5 km around each neighbourhood), prices are realistic in USD, and photos are generated placeholders.

## What to try (milestone 1)

1. **Home page** (`/`): the hero search, featured homes and the "Explore by city" grid.
2. **Sign up** (`/accounts/signup/`): pick one or more roles. Choosing Agency asks for an agency name. The verification email prints in the `runserver` console. Open the link to verify.
3. **Sign in** as each demo account (`/accounts/login/`). Each role lands on its own dashboard. The seller account holds two roles and can switch between the Seller and Buyer dashboards.
4. **Password reset** (`/accounts/password/reset/`): the reset link prints in the console.
5. **Staff sign-in** (`/accounts/staff/login/`): only staff accounts get in. Non-staff accounts are refused.
6. **Search** (`/search/`): see the milestone 3 notes below.
7. **Design system** (`/styleguide/`, only when `DEBUG=True`).

## What to try (milestone 2: listings core)

1. **Listing page**: click any card. You'll see the photo gallery (click a photo, then use the arrow keys and Esc), price, key facts, description, amenities, location, the agent/owner card and similar homes.
2. **Listing limits**: sign in as the **landlord**. The dashboard shows 2 / 2 active slots. Click **Submit for review** on the Kigali draft and you'll be refused because all slots are used. Click **Mark as rented** on a live listing, then submit the draft again: it goes into review.
3. **The seller** has 1 free slot (1 / 1 used) and a draft that can't be submitted until the live one is marked sold.
4. **Create a listing**: on the dashboard, choose **New listing**. Fill it in, optionally add photos, and save it as a draft. On the edit page you can upload more photos, drag to reorder them, make one the cover, or delete one. The sidebar lists what's still missing before you can submit.
5. **Editing a live listing** sends it back to review (see QUESTIONS.md Q11).
6. **Preview**: owners can open their own drafts. Everyone else gets a 404 until the listing is published.
7. **Agents** can prepare drafts but can't submit until subscriptions arrive in milestone 6 (QUESTIONS.md Q12).

The map pin picker and the map on the listing page appear once `MAPBOX_TOKEN` holds a real public token. Until then, the form takes latitude and longitude as numbers.

## What to try (milestone 3: search and map)

1. **Search** (`/search/`): change any filter and the results update in place, with a clean, shareable URL. Filters: buy/rent, city, price range, bedrooms and sort in the bar; type, bathrooms, furnished, area, neighbourhood, distance and amenities under **More filters**.
2. **Distance**: choose a city, then **More filters → Within 10 km**. Without a map, distance is measured from the centre of that city's listings (PostGIS).
3. **Favorites**: sign in as the **buyer** or **renter**. Tap a heart on any card or listing page. Saved homes appear on the dashboard and under **Saved** in the header.
4. **Saved searches**: run a search and choose **Save search**. Saved searches appear on the buyer/renter dashboard and at `/my/searches/`, where you can turn the daily email on or off or delete them. The renter starts with one saved search ("Rent · Lagos · 2+ beds").
5. **Daily digest**: run `python manage.py shell -c "from apps.search.digest import send_digests; print(send_digests())"` after publishing a new matching listing. The email prints in the console.
6. **Renters** land on rentals by default.

**Map (needs `MAPBOX_TOKEN`)**: with a real token the search page becomes a split view: results on the left and a map on the right with price-bubble pins. Clicking a pin opens a preview card, hovering a card highlights its pin, you can draw an area or use **Search this area**, distance is measured from the map centre, and on phones a **Show map / Show list** button switches views.

## Recorded walkthrough

A scripted shot list for the recorded walkthrough is added in milestone 8 (see QUESTIONS.md, Q7).
