---
version: 1
name: InterROS Postfix Admin
inspired_by: HashiCorp (VoltAgent/awesome-claude-design catalog)
description: Dark-first operations console for an already-installed Postfix. Near-black canvas, charcoal surface ladder, hairline borders, one cyan identity accent for mail/relay. Engineered 8px controls, not consumer pills.
---

# InterROS Postfix Admin — DESIGN.md

Source of truth for UI. Catalog: `vendor/awesome-claude-design/`. Inspiration: HashiCorp entry (enterprise infrastructure, black canvas, surface lift, 8px CTAs). Original product identity: InterROS + cyan mail accent.

## 1. Visual Theme & Atmosphere

Dense operator UI for mail infrastructure. Quiet, technical, keyboard-friendly. Hierarchy comes from a surface ladder (canvas → card → lifted row), not drop shadows or gradients. One chromatic accent only. Data tables are first-class: full width of the content column, high-contrast text, wrapping raw log lines.

Mood: night NOC, not marketing site. Login is a compact card, not a hero.

## 2. Color Palette & Roles

### Dark (default)

| Token | Hex | Role |
|---|---|---|
| canvas | `#000000` | Page, topbar, footer |
| surface-1 | `#15181e` | Cards, sidebar, table body |
| surface-2 | `#1f232b` | Inputs, hover, striped rows |
| surface-3 | `#3b3d45` | Strong hairline / dividers |
| hairline | `rgba(178,182,189,0.14)` | Card and table borders |
| ink | `#ffffff` | Titles, primary text |
| ink-muted | `#b2b6bd` | Labels, secondary, raw logs |
| ink-subtle | `#656a76` | Eyebrows, hints |
| accent | `#14c6cb` | Primary CTA, focus, active nav, links |
| accent-hover | `#12b6bb` | Primary hover |
| success | `#00ca8e` | sent / up |
| warning | `#ffcf25` | deferred / warn |
| danger | `#e62b1e` | bounce / error |

### Light

| Token | Hex |
|---|---|
| canvas | `#f4f5f7` |
| surface-1 | `#ffffff` |
| surface-2 | `#eef0f3` |
| ink | `#0b0c0f` |
| ink-muted | `#3b3d45` |
| hairline | `rgba(15,23,42,0.14)` |
| accent | `#0e8f94` |

Never: cyan fills on entire cards; second brand hue; white text on dark-cyan-on-dark-gray sandwiches; Bootstrap default blue primary.

## 3. Typography Rules

Substitute for proprietary sans: **Inter** (400/500/600/700). Mono for raw logs and config: **IBM Plex Mono** or `ui-monospace`.

- Page title: 22–28px, weight 600, tracking −0.4px, ink
- Body / table: 14–16px, weight 500, line-height 1.5
- Nav / eyebrow: 12px, weight 600, letter-spacing 0.06em, uppercase, ink-subtle
- Raw log cell: 12.5px mono, ink-muted, wrap (`pre-wrap` + `overflow-wrap: anywhere`)
- Login heading: 20px, weight 600, not all-caps mega title

## 4. Component Stylings

- **Buttons:** radius 8px. Primary = accent fill, white text. Secondary = surface-2, ink text. Danger = danger fill.
- **Cards:** surface-1, 12px radius, 1px hairline, no heavy shadow.
- **Inputs:** surface-2, 8px radius, ink text, hairline border; focus ring 2px accent at 35% opacity.
- **Sidebar:** surface-1, active link = accent text + 12% accent wash. Logo 40px in nav, 64px on login (not full-card).
- **Tables:** 100% width of card; thead ink-muted; cells inherit ink; striped surface-2; hover 10% accent. No nested max-width on page that shrinks tables to ~50%.
- **Badges:** pill only for status chips.
- **Alerts / toasts:** surface-1 + left accent bar (success/warning/danger/accent).

## 5. Layout Principles

- Sidebar sticky 16.5rem; content column `flex: 1; min-width: 0; width: 100%`.
- Page padding 24px (16px on small screens).
- Logs / queue / users: table lives edge-to-edge inside the card (`card-body p-0`).
- 8px spacing scale: 4 / 8 / 12 / 16 / 24 / 32.

## 6. Depth & Elevation

Prefer surface lift over shadow. Optional shadow: `0 1px 0 rgba(255,255,255,0.04) inset` plus hairline. Login card may use a faint 24px black wash.

## 7. Do's and Don'ts

Do: keep text contrast ≥ WCAG AA on canvas and surfaces; wrap long emails and raw syslog; keep primary actions cyan and rare.

Don't: put dark gray text on dark surfaces; constrain `.page-container` to 1200px; inflate the login logo; mix Bootstrap unthemed white cards with the dark shell; use pill-shaped primary buttons.

## 8. Responsive Behavior

- &lt;992px: sidebar off-canvas; hamburger in topbar.
- Tables: horizontal scroll inside `.table-responsive`, never shrink the whole page.
- Touch targets ≥ 40px for icon buttons.

## 9. Agent Prompt Guide

When changing UI: read this file first, then `static/style.css`. Map tokens to CSS variables. Do not introduce a second accent. After CSS edits, bump `style.css?v=` in `templates/base.html`.
