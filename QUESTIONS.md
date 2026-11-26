# Open questions

Each question lists the default I am using until you answer, so work is not blocked.

## Q1. Seller vs landlord limits
SPEC section 2 groups "individual owner / seller / landlord" into one row but gives different free limits (landlord 2, seller 1). Demo accounts list "individual seller" and "landlord" separately.
**Default:** two separate role flags, `seller` and `landlord`. Free active listing allowance = 1 if seller, 2 if landlord, 3 if both. Confirm, or tell me if the limit should depend on listing purpose instead (sale listings count against 1, rent listings against 2).

## Q2. Email verification gate
SPEC requires email verification but does not say what an unverified user can do.
**Default:** unverified users can log in and browse, but must verify before creating listings, sending inquiries, or messaging. A banner prompts them to verify.

## Q3. Renter role
"Same as buyer, filtered to rentals."
**Default:** renters see the rent purpose preselected in search and on the home hero. They can still switch to buy.

## Q4. Plan prices, featured pricing, subscription tiers
SPEC does not give amounts or durations.
**Default (placeholders, editable in admin settings in milestone 8):** extra listing $10 for 30 days; featured placement $25 for 14 days; Agent plan $29/month, 15 active listings; Agency Starter $99/month, 3 seats, 50 listings; Agency Pro $249/month, 10 seats, 200 listings.

## Q5. Listing expiry
Lifecycle includes "expired" but no duration is given.
**Default:** published listings expire 90 days after publishing; owners can renew.

## Q6. Demo photos (resolved)
Demo listings use 41 real photos (apartments, villas, townhouses, interiors) from Unsplash, free under the Unsplash License, stored in `seed_assets/photos/` with sources in `seed_assets/photos/CREDITS.md`. No Unsplash+ (paid) images. If the folder is missing, `seed_demo` falls back to generated drawings.

## Q7. Recorded walkthrough (milestone 8)
I cannot record a screen video. **Default:** I will write a scripted walkthrough (shot list and narration) in DEMO.md; a person records it.

## Q8. Photo storage
**Default:** local disk under `MEDIA_ROOT` on the VPS, served by Nginx. No S3 in phase 1.

## Q9. Local environment (decided)
The owner turned off Smart App Control, so development runs natively on Windows: portable PostgreSQL 16.16 + PostGIS 3.7 in `C:\Users\10adn\advoxy-devtools` (two missing GDAL DLLs copied from Git for Windows), Python 3.12 venv in `.venv`, Celery inline (`CELERY_TASK_ALWAYS_EAGER=True`), no local Redis. `scripts/dev_setup_ubuntu.sh` covers Ubuntu/WSL and mirrors the VPS.

## Q10. Data export and account deletion
SPEC section 1 asks for consent, data export, deletion, and minimal data collection, but section 13 has no task for export/deletion.
**Default:** consent (terms + privacy acceptance, optional marketing opt-in, timestamped) ships in milestone 1 signup. Self-service data export (JSON download) and account deletion ship in milestone 8 alongside the polish tasks.

## Q11. Editing a live listing
SPEC says moderation gates publishing but not what happens when an owner edits a published listing.
**Default:** content edits to a published listing send it back to "pending review"; it stays hidden until approved again. Saving without changes keeps it live. Photo changes do not trigger re-review.

## Q12. Agents and agencies before billing (milestone 6)
Agents and agencies need an active subscription to list. Plans and subscriptions arrive in milestone 6.
**Default:** until then their capacity is 0: they can create and edit drafts, but cannot submit for review. Seeded agent listings stay published.

## Q13. Mapbox token (resolved)
A real public token is now in `.env`. The search map, listing-form pin picker and listing-page map are verified. For production, restrict the token to the live domain in the Mapbox dashboard (URL restrictions).

## Q14. Saved-search digest timing
SPEC asks for a daily digest but not when.
**Default:** 06:00 UTC daily (morning across most of Africa). One email per user covering all their saved searches, only listings published since the last digest, up to 6 per search with a "see all" link.

## Q15. Call and WhatsApp buttons on listing cards
Bayut's cards have Email, Call and WhatsApp buttons. SPEC only covers the inquiry form and in-app messaging, and showing phone numbers raises privacy questions.
**Default:** cards show one **Contact** button that opens the listing's contact section (inquiry form arrives in milestone 4). Tell me if you want Call / WhatsApp buttons (phone number shown only if the owner or agent opts in).

## Q16. Look and feel changes (decided, Nov 26)
On the owner's request: switched to a single sans-serif font (Plus Jakarta Sans, set in `config/brand.py` + `static/brand/theme.css`); search results use detail-rich horizontal cards like Bayut; the search page opens as a list, with a List/Map toggle (listings left, map right) and an "Expand map" full-width view; the home hero has Buy/Rent, location, Property type, Beds & baths and Price dropdowns. Seed data and city lists focus on priority markets in this order (setting `PRIORITY_COUNTRIES`): Nigeria, Kenya, South Africa, Ghana, Ethiopia, Senegal, DR Congo, Somalia, Sudan. Bayut's "Yearly rent" and "Ready / Off-plan" options are not included because the data model has monthly rent only and no completion status; say if you want them.

## Q17. Real photos for demo listings (resolved)
Done, see Q6. The home page hero image is a brand setting (`BRAND["hero_image"]`, file `static/brand/hero.jpg`).

## Q18. Messaging defaults (milestone 4)
- **Who can send inquiries:** signed-in users with a verified email (Q2). Visitors see a "Sign in to contact" button. The form is prefilled from their account; name, email, phone and message are shared with the lister.
- **One conversation per listing per person:** a second inquiry on the same listing continues the same thread.
- **Spam guard:** at most 20 inquiries per person per day.
- **Email throttling:** new-message emails go out at most once every 15 minutes per conversation while the recipient still has unread messages; reading the conversation resets this.
- **Polling:** the open conversation, the conversation list and the header unread badge refresh every 5 seconds, only while the browser tab is visible.
- **Agency owners** do not see their agents' conversations yet. Tell me if they should (milestone 7, agency teams).

