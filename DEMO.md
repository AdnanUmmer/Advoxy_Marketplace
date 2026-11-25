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
6. **Search stub** (`/search/?city=Nairobi&purpose=rent`) and a **listing page** (click any card). Both are simple placeholders until milestones 2 and 3.
7. **Design system** (`/styleguide/`, only when `DEBUG=True`).

## Recorded walkthrough

A scripted shot list for the recorded walkthrough is added in milestone 8 (see QUESTIONS.md, Q7).
