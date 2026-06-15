# AttenDANCE — Design Audit (Phase 0)

_Studio management web app for LaShelle's School of Dance. Flask + Jinja + Tailwind (CDN) + Alpine + Font Awesome + Chart.js. PWA on a 256 MB Fly.io box._

---

## 1. Page / route inventory

Grouped by audience and function. Source: `app/main/routes.py`, `app/auth/routes.py`, templates in `app/templates/`.

### Public (no login)
| Route | Template | Purpose |
|---|---|---|
| `/register` | `registration/public.html` | Self-registration / enroll request |
| `/login` | `auth/login.html` | Sign in |

### Auth / account (any user)
| Route | Template | Purpose |
|---|---|---|
| `/auth/profile` | `auth/profile.html` | Your profile |
| `/auth/change_password` | `auth/change_password.html` | Change password |
| `/auth/register` | `auth/register.html` | Account creation |

### Parent portal
| Route | Template | Purpose |
|---|---|---|
| `/parent` | `parent/dashboard.html` | **Home** — per-child cards, balances, pay, attendance, company/recital/costumes/makeups/donate (all lazy-loaded) |
| `/students/<id>/statement` | `statements/student.html` | Account statement |
| `/giving-statement` | `statements/giving.html` | Tax/giving statement |
| `/rules/acknowledge/<id>` | `rules/acknowledge.html` | Initial studio rules |
| `/students/<id>/sign-waivers` | `waivers/sign.html` | Sign forms/waivers |
| `/students/<id>/certificate` | `skills/certificate.html` | Progress / skills certificate |

### Staff back office (admin + teacher)
| Route | Template | Group |
|---|---|---|
| `/dashboard` | `dashboard.html` | Overview |
| `/analytics` (admin) | `analytics/dashboard.html` | Overview — "Insights" |
| `/students` | `students/list.html` | People |
| `/students/<id>/detail` | `students/detail.html` | People |
| `/families` | `families/list.html` | People |
| `/families/<id>/ledger` | `families/ledger.html` | People |
| `/staff` (admin) | `staff/list.html` | People |
| `/leads` (admin) | `leads/manage.html` | People — "Leads & Trials" |
| `/classes` | `classes/list.html` | Classes & Attendance |
| `/calendar` | `calendar/view.html` | Classes & Attendance |
| `/take-attendance` (+`/<id>`) | `attendance/take_pick.html`, `attendance/take.html` | Classes & Attendance |
| `/attendance` | `attendance/list.html` | Classes & Attendance |
| `/makeups` (admin) | `makeups/manage.html` | Classes & Attendance |
| `/skills` (admin) | `skills/manage.html` | Classes & Attendance |
| `/transactions` | `transactions/list.html` | Money — "Payments" |
| `/pending-payments` (admin) | `payments/pending.html` | Money |
| `/settings` (admin) | `settings/payments.html` | Money — payment methods |
| `/donations` (admin) | `donations/admin.html` | Money |
| `/recital-hub` | `recital/hub.html` | Performance |
| `/recital` (admin) | `recital/manage.html` | Performance — costumes & tickets |
| `/recital/<id>/booklet` | `recital/booklet.html` | Performance — print booklet |
| `/company` (admin) | `company/manage.html` | Performance |
| `/locations` (admin) | `locations/list.html` | Studio |
| `/registrations` (admin) | `registration/admin.html` | Studio — "Enroll requests" |
| `/waivers` (admin) | `waivers/admin.html` | Studio — "Forms" |
| `/rules` | `rules/admin.html` | Studio |
| `/messages` | `messages/list.html` | Studio |
| `/timeclock` | `timeclock/view.html` | Studio |

**~30 staff routes** crammed into one nav. Errors: `errors/404.html`, `errors/500.html`.

---

## 2. The worst inconsistencies

1. **No shared component layer.** Every page re-implements its own page header (`bg-white shadow` → `max-w-7xl` → `h1.text-3xl` + subtitle), its own white card (`bg-white shadow-lg rounded-lg`), its own table, its own modal. Nothing is a macro/partial. Changing a button means editing dozens of files.

2. **Three different toast/flash systems.** `base.html` flash (fixed top-right, `animate-pulse`, hidden via `display:none` after 5 s), parent portal `#toast` (inline banner, scrolls to top), recital `#msg` (inline banner, 4 s). Different markup, different timing, different placement.

3. **`prompt()` / `alert()` / `confirm()` for real data entry.** Parent makeup request (2× `prompt`), donations (2× `prompt`), recital "New Year" (2× `prompt`), add number/award via `prompt`, `alert(d.error)` on save failures, `confirm()` for every delete. Sits next to proper modals (student add/edit, pay) and inline forms (recital awards/ads) — three create/edit paradigms in one app.

4. **Color drift.** Brand is indigo `#6366f1` (`primary`), but buttons appear in `amber-500` (pay), `rose-500` (donate), `indigo-600` (combined pay), `gray-800` (booklet), `primary-600` (everything else). Stat-card icons use `blue/green/purple/red-100` arbitrarily. Status pills, info banners, and accents each pick their own hue.

5. **Two JS philosophies.** Alpine (nav, recital tabs, flash transitions) vs hand-rolled vanilla `fetch` + `innerHTML` string templates (students, parent, recital). HTML is authored twice — once in Jinja, once in JS template literals — with separate `esc()` helpers copy-pasted per file.

6. **Navigation overload.** ~18 top-nav links for an admin, plus a user dropdown that hides Skills, Makeups, Leads, Insights, Settings (unrelated items lumped together), plus a fully duplicated mobile menu. No grouping; ordering is historical, not functional. Two "home" icons (Dashboard + Families both `fa-home`).

7. **Tables reinvented each time** with the same `min-w-full divide-y divide-gray-200` + `thead.bg-gray-50` + uppercase `th`, but no shared markup — and no consistent empty/loading state (`Loading students…`, `Loading…`, `No recital yet` each styled differently).

8. **Inconsistent density & type.** `text-3xl` page titles, `text-lg` section heads, `text-sm`/`text-xs` body — but applied unevenly. Font is the browser default sans (no type system).

---

## 3. Proposed information architecture

Replace the top-nav + dropdown with a **persistent grouped left sidebar** (staff, desktop) that collapses to a drawer on mobile, and a **focused parent portal** with a bottom tab bar on phones.

### Staff sidebar groups
- **Overview** — Dashboard · Insights
- **People** — Students · Families · Staff · Leads & Trials
- **Classes & Attendance** — Classes · Calendar · Take Attendance · Attendance Log · Makeups · Skills
- **Money** — Payments · Pending · Payment Methods · Donations
- **Performance** — Recital Hub · Company · Booklet
- **Studio** — Locations · Enrollment Requests · Forms & Waivers · Rules · Messages · Time Clock

Profile, change password, and sign-out move to a **user menu pinned to the sidebar footer** (not mixed with feature pages).

### Parent portal
Single clean home (per-child cards + sticky balance/pay), with a 5-item bottom tab bar on mobile: **Home · Pay · Calendar · Forms · More**. No studio chrome, no back-office links.

---

## 4. Design direction (summary)

Refine the existing **brand purple + champagne gold** language (already prototyped for the attendance PWA) into a full system, replacing the indigo. Warm neutral surfaces, **DM Serif Display** for titles/greetings + **Atkinson Hyperlegible** for all UI/body (chosen for legibility → WCAG 2.2 AA). Gold is reserved for prestige/celebration moments only. One button system, one table, one modal, one toast. Full tokens, type scale, and component set are shown in the Phase 0 direction document.
