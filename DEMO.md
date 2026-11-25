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
6. **Search stub** (`/search/?city=Nairobi&purpose=rent`): a simple grid until milestone 3.
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

## Recorded walkthrough

A scripted shot list for the recorded walkthrough is added in milestone 8 (see QUESTIONS.md, Q7).
