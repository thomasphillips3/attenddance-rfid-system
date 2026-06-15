# Recital Hub — Feature Plan

**Type:** Brownfield feature (AttenDANCE / Flask)
**Goal:** One per-year place to organize the annual recital — show order, music & choreography, student awards, and a printable booklet with custom ads — reusing the existing `Costume` and `TicketType`/`Performance` infrastructure rather than duplicating it.

---

## Requirements

| ID | Requirement |
|----|-------------|
| REC-01 | Admin can create a recital per year (title, theme, date, show times, venue, director's note, acknowledgments) and mark exactly one **active**. |
| REC-02 | Staff can build the **show order** — add numbers, reorder them, group by act, flag the finale. |
| REC-03 | Each number holds **music** (song, artist, audio link, cue notes) and **choreography** (choreographer, notes, link, formation, duration, props). Editable by **any staff** (admin or teacher). |
| REC-04 | Staff assign **dancers to each number** (cast) — "fill from class/group" in one click, plus add/remove individuals and label parts (solos). |
| REC-05 | Admin records **student awards** (title, category, recipient, description, order). |
| REC-06 | Admin creates **booklet ads** (advertiser, size, price, ad copy, uploaded image, "in honor of" dancer, paid status). |
| REC-07 | System generates a **printable booklet** — cover, director's note, program (ordered numbers + cast), awards, ads, acknowledgments. |
| REC-08 | Recital **links existing Costumes and Tickets/Performances** so it's all one place. |
| REC-09 | Parents see a **read-only recital section** — show dates/call times, the full program, and which numbers their own dancer is in. |

### Out of scope (v1)
- Parent/sponsor **self-service** ad submission + ledger billing — deferred (admin enters ads for now).
- Per-teacher class-ownership permissions — any staff can edit (per decision).
- Hosting/uploading **audio files** — use shared links (Drive/Dropbox). Keeps us off the 256 MB box's disk.
- Ticket-sales redesign — reuse existing `TicketType`/`TicketOrder`.

---

## Data Model (5 new tables + 1 column)

**`Recital`** — annual container
`year`(int, idx), `title`, `theme`, `recital_date`, `show_times`(str, e.g. "Matinee 2 PM · Evening 6 PM"), `venue`, `director_note`(text), `acknowledgments`(text), `cover_image_data`(text/data-URI), `ad_pricing_note`(text), `is_active`(bool), `is_locked`(bool), `created_at`.

**`RecitalNumber`** — one routine = show-order row **and** the music/choreo record
`recital_id`, `order_index`, `title`, `class_id?`, `group_id?`, `style`, `act?`, `song_title`, `song_artist`, `music_url`, `music_notes`, `choreographer`, `choreo_notes`, `choreo_url`, `duration`, `props`, `formation_notes`, `is_finale`, `notes`, `created_at`.

**`RecitalCast`** — dancer in a number
`number_id`, `student_id`, `part?`, `created_at`. Unique(`number_id`,`student_id`).

**`RecitalAward`**
`recital_id`, `title`, `category?`, `student_id?`, `recipient_text?`, `description`, `order_index`, `created_at`.

**`RecitalAd`**
`recital_id`, `advertiser`, `size`(full/half/quarter/business_card/shout_out), `price`, `content`, `image_data?`(data-URI), `contact_name?`, `contact_email?`, `student_id?`, `status`(submitted/approved/placed), `paid`, `paid_at?`, `order_index`, `created_at`.

**Column add:** `Performance.recital_id` (nullable FK → recitals) so existing show dates + ticketing attach to the hub. Idempotent `ALTER TABLE` in the startup migration (guarded like the others).

New tables come up via `db.create_all()`; the one column goes through the existing ALTER-migration path.

---

## Phases & Tasks

### Phase 1 — Data model & migration
1. Add the 5 models + `Performance.recital_id` to `app/models.py`.
2. Add the guarded `ALTER TABLE performances ADD COLUMN recital_id` to the startup migration.
3. Boot app on a throwaway DB → confirm tables + column appear, idempotent on second boot.

### Phase 2 — Hub backend (API, `app/api/routes.py`)
- Recitals: `GET/POST /recitals`, `PUT/DELETE /recitals/<id>`, `POST /recitals/<id>/activate` (POST/PUT/DELETE/activate = admin).
- Numbers (staff): `GET/POST /recitals/<id>/numbers`, `PUT/DELETE /recital-numbers/<nid>`, `POST /recitals/<id>/numbers/reorder`.
- Cast (staff): `GET/POST /recital-numbers/<nid>/cast`, `POST /recital-numbers/<nid>/fill-from-class`, `DELETE /recital-cast/<cid>`.
- Awards (admin): `GET/POST /recitals/<id>/awards`, `PUT/DELETE /recital-awards/<aid>`.
- Ads (admin): `GET/POST /recitals/<id>/ads`, `POST /recital-ads/<aid>/image` (data-URI upload, mirrors the Zelle-QR endpoint), `PUT/DELETE /recital-ads/<aid>`.
- Link: `POST /recitals/<id>/link-performance` (admin).
- All mirror existing patterns: `login_required`, `_admin_only()` guard for admin actions, JSON in/out, `AuditLog.record` on mutations.

### Phase 3 — Hub UI
- `templates/recital/hub.html` — Alpine.js tabbed page (Overview · Show Order · Awards · Booklet & Ads), Tailwind/Font-Awesome, fetch-based, matching existing admin pages. Admin-only controls gated with `current_user.is_admin`.
- Page route `/recital-hub` (`@staff_required`) in `app/main/routes.py`.
- `templates/base.html` nav — "Recital" → hub; Costumes & Tickets linked from inside the hub (existing `/recital` kept).

### Phase 4 — Booklet
- `templates/recital/booklet.html` — print-optimized (like `statements/*` and `skills/certificate.html`): cover, director's note, program (ordered numbers + cast list), awards, ads grid (renders uploaded images), acknowledgments.
- Route `/recital/<id>/booklet` (`@staff_required`).

### Phase 5 — Parent view
- `GET /api/my-recital` — active recital + program + the parent's dancers' numbers + call times (read-only).
- Add a "Recital" section to `templates/parent/dashboard.html`.

### Phase 6 — Verify, commit, deploy
- Local smoke test (testing config, in-memory) of model creation + key endpoints.
- `python -m py_compile` on changed Python.
- Conventional commit; push + `flyctl deploy`; curl smoke-test; `flyctl logs` check (watch for OOM regression — single gthread worker stays).
- Update `MEMORY.md` (new models + routes + hub).

---

## Success Criteria
1. Admin creates a 2026 recital and marks it active.
2. Staff add numbers, reorder them, attach a class, **fill cast from the class**, and record song + audio link + choreo notes.
3. Admin adds at least one award and one ad (with image).
4. `/recital/<id>/booklet` renders a print-ready booklet with the ordered program + cast, awards, and ads.
5. A parent sees show dates/call times and their own dancer's numbers; sees nothing editable.
6. Existing Costumes/Tickets still work and are reachable from the hub; app boots clean with new tables + `recital_id` (migration idempotent).

## Risks
- **256 MB Fly box:** no new dependencies (all existing/stdlib). Ad images stored as data-URIs in the DB (same as the Zelle QR); cap/validate ad-image size and warn on large uploads so the booklet page and DB stay reasonable.
- **Migration idempotency:** wrap the `recital_id` ALTER in try/except like the existing column migrations.
- **No regressions:** keep the existing `/recital` (costumes/tickets) route and templates untouched; the hub links to them.

---

## CCA exam takeaway
Brownfield feature design = **extend the existing domain model, don't fork it.** Reusing `Performance`/`Costume` via one nullable FK (`Performance.recital_id`) instead of cloning a parallel "show" concept keeps the schema coherent — the architectural equivalent of composing tools around a shared context rather than duplicating state.
