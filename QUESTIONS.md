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

## Q6. Demo photos
"Placeholder photos" for 60+ seeded listings. Real photography looks far better for a premium demo, but hot-linking or downloading stock photos raises licensing and network questions.
**Default:** the seed command generates local placeholder images (soft architectural gradients with the listing type), no network needed. If you want real photos, tell me the source (for example, a licensed set you provide in a folder).

## Q7. Recorded walkthrough (milestone 8)
I cannot record a screen video. **Default:** I will write a scripted walkthrough (shot list and narration) in DEMO.md; a person records it.

## Q8. Photo storage
**Default:** local disk under `MEDIA_ROOT` on the VPS, served by Nginx. No S3 in phase 1.

## Q9. Local environment (decided)
The owner turned off Smart App Control, so development runs natively on Windows: portable PostgreSQL 16.16 + PostGIS 3.7 in `C:\Users\10adn\advoxy-devtools` (two missing GDAL DLLs copied from Git for Windows), Python 3.12 venv in `.venv`, Celery inline (`CELERY_TASK_ALWAYS_EAGER=True`), no local Redis. `scripts/dev_setup_ubuntu.sh` covers Ubuntu/WSL and mirrors the VPS.

## Q10. Data export and account deletion
SPEC section 1 asks for consent, data export, deletion, and minimal data collection, but section 13 has no task for export/deletion.
**Default:** consent (terms + privacy acceptance, optional marketing opt-in, timestamped) ships in milestone 1 signup. Self-service data export (JSON download) and account deletion ship in milestone 8 alongside the polish tasks.
