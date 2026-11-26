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
| Independent agent | `agent@demo.example.com` | Verified, Agent plan |
| Agency owner | `agency@demo.example.com` | Meridian Homes (verified), Agency Pro plan |
| Agency agent 1 | `agency.agent1@demo.example.com` | Verified |
| Agency agent 2 | `agency.agent2@demo.example.com` | Verified |
| Agency agent 3 | `agency.agent3@demo.example.com` | Verification pending |

The seed creates 77 listings across 11 cities in the priority countries: Lagos and Abuja (Nigeria), Nairobi (Kenya), Johannesburg and Cape Town (South Africa), Accra (Ghana), Addis Ababa (Ethiopia), Dakar (Senegal), Kinshasa (DR Congo), Mogadishu (Somalia) and Khartoum (Sudan). Coordinates are real (jittered about 1.5 km around each neighbourhood), prices are realistic in USD, and each listing has five real photos (two exteriors, three interiors) from Unsplash (free licence; sources in `seed_assets/photos/CREDITS.md`).

## What to try (milestone 1)

1. **Home page** (`/`): the hero search (Buy/Rent, location, Property type, Beds & baths, Price), featured homes and the "Explore by city" grid, with priority countries first.
2. **Sign up** (`/accounts/signup/`): pick one or more roles. Choosing Agency asks for an agency name. The verification email prints in the `runserver` console. Open the link to verify.
3. **Sign in** as each demo account (`/accounts/login/`). Each role lands on its own dashboard. The seller account holds two roles and can switch between the Seller and Buyer dashboards.
4. **Password reset** (`/accounts/password/reset/`): the reset link prints in the console.
5. **Staff sign-in** (`/accounts/staff/login/`): only staff accounts get in. Non-staff accounts are refused.
6. **Search** (`/search/`): see the milestone 3 notes below.
7. **Design system** (`/styleguide/`, only when `DEBUG=True`).

## What to try (milestone 2: listings core)

1. **Listing page**: click any card. You'll see the photo gallery (click a photo, then use the arrow keys and Esc), price, key facts, description, amenities, location, the agent/owner card and similar homes.
2. **Listing limits**: sign in as the **landlord**. The dashboard shows 2 / 2 active slots. Click **Submit for review** on the Dakar draft and you'll be refused because all slots are used. Click **Mark as rented** on a live listing, then submit the draft again: it goes into review.
3. **The seller** has 1 free slot (1 / 1 used) and a draft that can't be submitted until the live one is marked sold.
4. **Create a listing**: on the dashboard, choose **New listing**. Fill it in, optionally add photos, and save it as a draft. On the edit page you can upload more photos, drag to reorder them, make one the cover, or delete one. The sidebar lists what's still missing before you can submit.
5. **Editing a live listing** sends it back to review (see QUESTIONS.md Q11).
6. **Preview**: owners can open their own drafts. Everyone else gets a 404 until the listing is published.
7. **Agents** can prepare drafts but can't submit until subscriptions arrive in milestone 6 (QUESTIONS.md Q12).

Without a `MAPBOX_TOKEN`, the form takes latitude and longitude as numbers and the listing page shows coordinates instead of a map.

## What to try (milestone 3: search and map)

1. **Search** (`/search/`): results show as detailed rows (photos you can flip through, price, type, beds, baths, area, title, address, amenities, lister and listing age). Change any filter and the results update in place, with a clean, shareable URL. The bar has Buy/Rent/All, location, **Property type**, **Beds & baths** and **Price** dropdowns, and **More filters** (area, neighbourhood, distance, amenities). Below it: furnished, sort, and the **List / Map** toggle. The sidebar has email alerts and popular locations (priority countries first).
2. **Distance**: choose a city, then **More filters → Within 10 km**. Without a map, distance is measured from the centre of that city's listings (PostGIS).
3. **Favorites**: sign in as the **buyer** or **renter**. Tap a heart on any card or listing page. Saved homes appear on the dashboard and under **Saved** in the header.
4. **Saved searches**: run a search and choose **Save search**. Saved searches appear on the buyer/renter dashboard and at `/my/searches/`, where you can turn the daily email on or off or delete them. The renter starts with one saved search ("Rent · Lagos · 2+ beds").
5. **Daily digest**: run `python manage.py shell -c "from apps.search.digest import send_digests; print(send_digests())"` after publishing a new matching listing. The email prints in the console.
6. **Renters** land on rentals by default.

7. **Map**: click **Map** to switch to a split view, with listings on the left and a map with price-bubble pins on the right. **Expand map** shows the map full width; **Show listings** brings the list back. The page remembers your choice.
   - Click a pin for a preview card. Hover a result card to highlight its pin.
   - Use the polygon tool (top left of the map) to draw an area, or pan the map and click **Search this area**.
   - The **Distance** filter measures from the map centre.
   - On phones, the **Show map / Show list** button switches views.
   - Links keep the drawn area, so a shared link opens the same search.
8. **Listing form**: click the map or drag the pin to set the location. The listing page shows the location on a map.

## What to try (milestone 4: inquiries and messaging)

1. **Inquiry**: sign in as the **buyer**, open any listing and use **Send an inquiry** in the contact card (or click **Contact** on a search result). It is prefilled from your account. After sending, the card confirms and links to the conversation. The owner's email (with your contact details) prints in the `runserver` console.
2. **Messages** (`/messages/`, or **Messages** in the header): the buyer, renter and independent agent each start with an unread reply, shown as a badge in the header and on the conversation.
3. **Live updates**: keep a conversation open as the buyer while someone replies (another browser signed in as `agency.agent1@demo.example.com`, or run `python manage.py shell -c "from apps.messaging.models import Thread; from apps.messaging.services import post_message; t = Thread.objects.first(); post_message(t, t.owner, 'Hello!')"`). The reply appears within 5 seconds without a refresh.
4. **Owners** see the inquirer's contact details at the top of the conversation.
5. **Email throttling**: several quick messages produce one email; the next one is sent after the recipient reads the conversation or 15 minutes pass.

## What to try (milestone 5: admin dashboard)

Sign in at `/accounts/staff/login/` as `admin@demo.example.com`.

1. **Overview** (`/staff/`): metric tiles, daily charts for new listings and inquiries (hover a bar, or **Show as table**), listings by status, users by role, recent activity. Toggle **Dark mode** in the sidebar (remembered; follows your system by default).
2. **Moderation**: listings waiting for review, oldest first, with photos and details. **Approve** publishes and emails the owner; **Request edits** and **Reject** need a note, which is emailed. Select several and **Approve selected** (with confirmation).
3. **Listings**: search (press `/` to jump to the box), filter by status, purpose, type, country or featured, sort any column, change rows per page. Tick rows and use **Bulk action** (feature, remove featured, unpublish, delete). A confirmation dialog appears; delete requires typing DELETE.
4. **Users**: search and filter by role or account state. Open a user to see their profile and listings, change roles, set the verification status, or suspend (they are signed out immediately and can't sign in).
5. **Verifications**: Jean-Paul Habimana (agency agent 3) has a license waiting. **Open license** shows the private file; approve, or reject with a reason (emailed).
6. **As an agent** (`agent@demo.example.com`): the dashboard has a **Verified badge** panel; when not verified, it offers a license upload (PDF/JPG/PNG).
7. **Tablet**: at tablet width the sidebar becomes a top bar and tables scroll inside their frame.

## What to try (milestone 6: payments)

Payments run in **Stripe test mode**: use card `4242 4242 4242 4242`, any future expiry, any 3-digit code. No real money moves.

1. **Pricing** (`/pricing/`, also in the header): free allowance, extra listing slot, featured placement and the three plans.
2. **Extra slot**: sign in as the **landlord** (2/2 slots used), open **Billing and plans** (dashboard link or `/billing/`), **Buy for $10**, pay on Stripe Checkout. You return to "Payment received", capacity becomes 2/3 and the Dakar draft can now be submitted. A receipt prints in the console.
3. **Featured placement**: on the edit page of any live listing, **Feature for 14 days · $25**. After paying, the listing has the Featured badge and shows first in search. It is unfeatured automatically when the time runs out (hourly task).
4. **Subscriptions**: sign in as the **agent** (on the Agent plan). To try a real Stripe subscription, **Cancel plan** (demo plans have no Stripe record, so they end immediately) and choose the Agent plan again. Then **Cancel plan** keeps access until the period end and **Keep my plan** undoes it.
5. **Agency plan sharing**: agency agents publish under Meridian Homes' Agency Pro plan (200 listings shared by the team).
6. **Admin → Payments** (`/staff/payments/`): revenue this month, monthly recurring revenue, subscriptions and payments with links into the Stripe dashboard for refunds. The overview's revenue tile is now live.

## What to try (milestone 7: agencies and agents)

1. **Agent directory** (`/agents/`, **Agents** in the header): search by name, speciality or agency, filter by city, agency or **Verified only**. Verified agents are listed first.
2. **Agent profile**: open any agent for their bio, contact details, stats and live listings. Listing pages link the agent's name and agency to these pages.
3. **Agencies** (`/agencies/`) and **Meridian Homes'** public page: description, contact, team and all team listings.
4. **Team management**: sign in as the **agency** and choose **Manage team** on the dashboard (`/my/team/`). Seats come from the plan (Agency Pro: 10). A demo invitation to `new.agent@demo.example.com` is pending. Invite any email: the invitation email prints in the console with its link. **Revoke** frees the seat; **Remove** takes an agent off the team (their listings stay with them).
5. **Joining**: sign in as the independent **agent**, then as the agency invite `agent@demo.example.com`. The agent's dashboard shows the invitation; accepting moves them and their listings under Meridian Homes. **Leave agency** on the dashboard undoes it.
6. **Edit profile** (dashboard link, `/accounts/profile/`): name, phone, city, bio and photo for everyone; licence, specialities and experience for agents; name, logo, description and contact for agencies. Photos are re-encoded so location data is removed.

## Sign in with Google

Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` (README, "Sign in with Google") and restart. **Sign in with Google** on `/accounts/login/` or **Sign up with Google** on `/accounts/signup/`. A new Google user lands on "Finish signing up" to choose roles; an existing email is linked and signed straight in.

## What to try (milestone 8: admin settings, audit log, emails)

Sign in at `/accounts/staff/login/` as the **admin**.

1. **Settings** (`/staff/settings/`): change the site name, upload a logo, switch currency (e.g. `KES`, `KSh `), change the featured price or free listing limits. The header, prices, pricing page, checkout and emails follow at once. Plans (price, listings, seats, offered) are edited on the right.
2. **Audit log** (`/staff/audit/`): every moderation decision, bulk action, user change, verification review and settings or plan edit, with who, when and what changed. Filter by area, date or text.
3. **Emails** (`/staff/emails/`): every transactional email with sample data, HTML and plain text.
4. **Dark mode**: the moon button in the admin sidebar.

## Recorded walkthrough (script, about 8 minutes)

I can't record video, so here is the shot list and narration (QUESTIONS.md, Q7). Record at 1440x900 with the demo data freshly seeded (`seed_demo --reset`).

| # | Screen | Do | Say |
|---|---|---|---|
| 1 | Home | Scroll the hero, switch Buy/Rent, open Property type and Price | "Advoxy lists homes for sale and rent across Africa, starting with the largest markets." |
| 2 | Search | Search Nairobi, rent, 2+ beds; open **Show map**, then full map; draw an area | "Every result shows the details people ask about first. The map shows only what's in view." |
| 3 | Listing | Open a listing; gallery, facts, amenities, map; agent card with Verified badge | "Verified means our team checked the agent's licence." |
| 4 | Inquiry | Sign in as **buyer**, send an inquiry; switch to the **agent** in another browser; reply | "Messages arrive within seconds and by email." |
| 5 | Saved | Save the home and the search | "Saved searches send a daily email of new matches." |
| 6 | Owner | Sign in as **landlord**; create a listing with photos; submit for review; show the 2/2 limit | "Individual owners list a few homes free." |
| 7 | Payments | Buy an extra slot with card 4242 4242 4242 4242; feature a listing | "Payments run through Stripe; we never see card numbers." |
| 8 | Agency | Sign in as **agency**; Manage team; invite an agent; show seats | "Agencies run their team and share one plan." |
| 9 | Admin overview | Sign in as **admin**; metrics, charts, activity | "Everything the team needs on one screen." |
| 10 | Moderation | Approve one listing, request edits on another with a note | "Owners get an email either way." |
| 11 | Users and verifications | Approve a licence; suspend and restore a user | |
| 12 | Settings and audit | Change the featured price; show it in the audit log and on the pricing page | "Prices, limits and branding change without code, and every change is recorded." |
| 13 | Close | Home page in dark admin and light public side by side | |
