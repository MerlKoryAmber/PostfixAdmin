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
| canvas | `#1a1a18` | Page, topbar, footer |
| surface-1 | `#242422` | Cards, sidebar, table body |
| surface-2 | `#1f1f1d` | Inputs |
| nav-item | `#2e2e2b` | Hover wash, secondary buttons |
| hairline | `#3d3d38` | Borders |
| ink | `#ecece6` | Titles |
| ink-body | `#c4c4be` | Body |
| ink-muted | `#8e8e86` | Labels, destructive outline |
| accent | `#3db8c6` | InterROS teal (из `c:\code\PostfixAdmin`) |
| accent-hover | `#5cc8d4` | Primary hover |
| accent-2 | `#cfcf2a` | Warning only |

### Light

| Token | Hex |
|---|---|
| canvas | `#f3f3ef` |
| surface-1 | `#ffffff` |
| surface-2 | `#ecece6` |
| ink | `#1a1a18` |
| ink-muted | `#5a5a54` |
| hairline | `#d0d0c8` |
| accent | `#3db8c6` |

Never: Bootstrap default blue (`#0d6efd`) or red (`#dc3545`); Google Fonts / any render-blocking CDN; HashiCorp product accents.

## 3. Typography Rules

Local stack: `"PT Sans", "Segoe UI", Helvetica, Arial` (woff2 в исходнике нет — без CDN). Mono: `ui-monospace`. html 16px, body 400 / line-height 1.45.

- Page title: 1.75rem / 700
- Body / table: 1.05rem
- Nav links: 1.125rem; sections 0.8rem uppercase
- Buttons: 0.95rem / 700 / uppercase / letter-spacing 0.03em; sm 0.875rem
- Labels: 0.875rem uppercase
- Login heading: 1.25rem / 700 / uppercase

## 4. Component Stylings

- **Buttons:** radius 8px. Primary/success/info = `#3db8c6` + white. Outline-primary fill on hover. Secondary = `#2e2e2b`. Warning = `#cfcf2a`. Danger = muted outline (`#5a5a54` / `#8e8e86`), not Bootstrap red.
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
