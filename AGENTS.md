# AGENTS.md — Dear Friends

## Goal

Dear Friends is a Russian-language illustrated friends-club site. The core visual feature is a sofa scene with individually authored SVG characters.

## Architecture

- Stack: plain HTML, CSS, JavaScript, SVG (no bundler, no package manager).
- Entry point: `index.html`. Most styles and code are intentionally inline.
- The repo root is deployed using GitHub Pages.
- `CNAME` configures the domain `dearfriends.ru`.
- Backend: Supabase (auth via magic-link email, Postgres tables with RLS,
  private `photos` storage bucket, realtime). Config: `SB_URL`/`SB_KEY`
  constants in `index.html`; schema lives in `supabase/schema.sql`.
- Motion: CSS keyframes + GSAP/ScrollTrigger + Lenis via CDN, with graceful
  fallback (no CDN or `prefers-reduced-motion` → no effects). Design language
  and motion rules live in `DESIGN.md` — read it before visual changes.

## Requirements for coding agents

1. Preserve all character artwork, names, interactions, and sofa positions unless the user specifically requests a change.
2. Preserve the existing visual direction, UI language (Russian), animation and responsive behavior.
3. Prefer incremental edits and reviewable Pull Requests; don't migrate frameworks without instruction.
4. The legacy `window.claude` / `claude.use('db')` / `claude.use('assets')` APIs are gone; shared data now goes through Supabase. Keep the graceful no-config fallback (demo mode) working when `SB_KEY` is not set.
5. Never commit API tokens, service-role secrets, private credentials or user-uploaded private data. The anon key is public-safe; the service_role key must never enter the repo.
6. Do not weaken the site's security: all access control lives in RLS policies (`supabase/schema.sql`), never in client-side checks. The `members` table is the invite allowlist.
7. When changing tables or policies, update `supabase/schema.sql` in the same change and keep it re-runnable.

## Check after every change

- Open `index.html` on desktop and mobile viewports.
- Confirm sofa characters, animation, responsiveness and light/dark theme.
- Verify event form, chat form, image gallery/lightbox and graceful no-Claude behavior.
- Confirm there are no JavaScript syntax errors or console crashes.

## Later refactor (optional)

Move CSS, JavaScript and SVG renderers into `styles.css`, `app.js`, `characters.js`, respectively, only if the change preserves rendering and behavior.
