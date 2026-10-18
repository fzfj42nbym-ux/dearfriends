# AGENTS.md — Dear Friends

## Goal

Dear Friends is a Russian-language illustrated friends-club site. The core visual feature is a sofa scene with individually authored SVG characters.

## Architecture

- Stack: plain HTML, CSS, JavaScript, SVG (no bundler, no package manager).
- Entry point: `index.html`. Most styles and code are intentionally inline.
- The repo root is deployed using GitHub Pages.
- `CNAME` configures the domain `dearfriends.ru`.

## Requirements for coding agents

1. Preserve all character artwork, names, interactions, and sofa positions unless the user specifically requests a change.
2. Preserve the existing visual direction, UI language (Russian), animation and responsive behavior.
3. Prefer incremental edits and reviewable Pull Requests; don't migrate frameworks without instruction.
4. The original `window.claude`, `claude.use('db')`, and `claude.use('assets')` APIs are not present on GitHub Pages. Avoid promising shared events/chat/gallery until an independent backend exists.
5. Never commit API tokens, service-role secrets, private credentials or user-uploaded private data.
6. Do not weaken the site's security or add client-side-only fake authentication. Pages is public; real access controls require an external service.
7. If building the backend, separate browser-safe public config from secrets; establish authorization, abuse protection, and sensible rate limits.

## Check after every change

- Open `index.html` on desktop and mobile viewports.
- Confirm sofa characters, animation, responsiveness and light/dark theme.
- Verify event form, chat form, image gallery/lightbox and graceful no-Claude behavior.
- Confirm there are no JavaScript syntax errors or console crashes.

## Later refactor (optional)

Move CSS, JavaScript and SVG renderers into `styles.css`, `app.js`, `characters.js`, respectively, only if the change preserves rendering and behavior.
