---
version: alpha
name: HashiCorp
website: "https://www.hashicorp.com"
description: "An enterprise-infrastructure marketing canvas built around a near-black ground (#000000) and a system of per-product accent colors — Terraform purple, Vault yellow, Consul pink, Waypoint cyan, Vagrant blue — that act as identity tokens rather than decorative palette. Display type is hashicorpSans set in 600/700 with tight 1.17–1.21 line-heights; body type runs the same family at 500 weight with relaxed 1.50–1.71 line-heights. Cards live as charcoal surfaces with 1px translucent gray borders; product showcase cards lift into per-product chromatic gradients. The system reads as confident, technical, and intentionally multi-product — every section quietly signals which HashiCorp tool it represents."

seo:
  title: "HashiCorp Design System for React — Black canvas, per-product accents, 22 components"
  metaDescription: "HashiCorp's design system as a DESIGN.md file. Black canvas #000000, hashicorpSans, 7 product accents, 22 components. For React, Next.js, and AI tools."
  highlights:
    - "Per-product identity palette — Terraform #7b42bc, Vault #ffcf25, Consul #e62b1e, Waypoint #14c6cb, Vagrant #1868f2, Nomad #00ca8e, Boundary #f24c53"
    - "Black-only marketing canvas — #000000 carries hero, body, pricing, and footer; no light mode in the public surface"
    - "Surface lift over shadow — canvas to surface-1 (#15181e) to surface-2 (#1f232b) handles elevation, never drop shadows"
    - "Engineered CTA shape — 8px rounded buttons, not pills; reads as developer-tool not consumer-app"
    - "One typeface across the scale — hashicorpSans at 500/600/700 carries display, body, and microcopy with no mono"
  tags:
    - "Backend, Database & DevOps"
    - "Developer Tools & IDEs"
  lastUpdated: "2026-05-12"
  author:
    name: "Dov Azencot"
    url: "https://x.com/dovazencot"
  opening: |
    HashiCorp's marketing brand is one of the most disciplined dark-canvas systems on the web. Every public page sits on pure black #000000, lifts to charcoal #15181e for cards, and uses a system of per-product accent colors — Terraform purple, Vault yellow, Consul red, Waypoint cyan, Vagrant blue, Nomad green, Boundary coral — to signal which tool a given section represents. The accents are identity tokens, not decoration: a Terraform card lifts onto a violet ground, a Vault card onto yellow, a Waypoint card onto cyan. A reader scrolling the homepage can tell which product a section belongs to from the corner of their eye, before reading a single word.

    This page packages all of that into a single DESIGN.md file. Inside: 32 color tokens grouped into brand, surface, hairline, text, per-product identity, and semantic bands; 12 typography styles spanning an 80px display down to 12px eyebrow; 8 corner-radius tokens; 9 spacing values built on an 8px base; and 22 components covering buttons (white, charcoal, ghost, and per-product variants), cards (feature, pricing, resource, and chromatic product cards), inputs, pills, comparison rows, CTA banners, navigation, and footer. The format is the Google Labs DESIGN.md spec.

    Feed the file to Claude, Cursor, or GitHub Copilot and the agent reproduces HashiCorp's specific discipline — black canvas, surface lift instead of shadow, 8px engineered corners, per-product identity surfaces — instead of a generic dark theme. Reference the tokens directly for Tailwind config, CSS variables, or your own component library. The system is worth studying because it solves a hard problem: a multi-product portfolio that has to feel coherent without flattening into a single house color.
  related:
    - href: "/design"
      title: "Browse all design systems"
      description: "The full directory of DESIGN.md files on shadcn.io, with live mockups for each."
    - href: "https://www.hashicorp.com/en/brand"
      title: "HashiCorp brand resources"
      description: "Official brand guidelines, product logomarks, and color spec from HashiCorp."
    - href: "https://github.com/google-labs-code/design.md"
      title: "The DESIGN.md specification"
      description: "Google Labs' open spec for machine-readable design system files — the format this page is built on."
  questions:
    - id: "primary-color"
      title: "What is HashiCorp's primary brand color?"
      answer: "HashiCorp's brand canvas is pure black #000000 — every marketing page, the footer, comparison tables, and the hero all sit on it. Instead of a single accent, the system uses a palette of per-product identity colors: Terraform purple #7b42bc, Vault yellow #ffcf25, Consul red #e62b1e, Waypoint cyan #14c6cb, Vagrant blue #1868f2, Nomad green #00ca8e, and Boundary coral #f24c53. Each product gets its own button and card variant; the accents are reserved for that product's sections."
    - id: "dark-mode"
      title: "Does HashiCorp have a light mode?"
      answer: "No — HashiCorp's marketing surface is dark-only. Canvas is #000000, cards lift to #15181e charcoal (surface-1), featured cards lift again to #1f232b (surface-2), and text is pure white #ffffff for headlines, #b2b6bd for secondary, and #656a76 for tertiary. Light-mode adaptation is documented as a known gap; the brand intentionally ships one mode."
    - id: "typography"
      title: "What typography does HashiCorp use, and what should I use if hashicorpSans isn't available?"
      answer: "HashiCorp runs hashicorpSans, a proprietary marketing typeface, across the entire scale — display, body, button, and caption. The spec walks through 12 type styles spanning 80px display down to 12px eyebrow, with weights at 500 body / 600 emphasis / 700 display. Inter is the closest open-source substitute; Geist Sans and IBM Plex Sans also work. Adjust line-heights down by roughly 0.02 to match hashicorpSans's slightly tighter proportions."
    - id: "shape-language"
      title: "Why does HashiCorp use 8px buttons instead of pills?"
      answer: "The brand reads as engineered, not consumer. CTAs sit at rounded.md (8px), feature and pricing cards at rounded.lg (12px), CTA banners at rounded.xxl (24px), and only small product chips use the pill radius. Pill-shaped primary buttons would read as fintech or consumer-app; 8px corners signal a developer-tool surface for infrastructure software."
    - id: "per-product-accents"
      title: "How do the per-product accent colors work?"
      answer: "Each HashiCorp product owns its own accent: Terraform purple, Vault yellow, Consul red, Waypoint cyan, Vagrant blue, Nomad green, Boundary coral. The accent appears on that product's section pill, its CTA button (button-product-terraform, button-product-vault, and so on), and where appropriate the showcase card background. The rule is strict — a Terraform-purple CTA on a Vault page is a brand violation, and the system never mixes two product accents in the same viewport."
    - id: "use-in-project"
      title: "Can I use this DESIGN.md to build my own React product?"
      answer: "Yes — the file is structured for AI tools. Feed it to Claude, Cursor, or Copilot and the agent will reproduce HashiCorp's specific discipline (black canvas, surface lift instead of shadow, 8px corners, per-product identity surfaces) rather than a generic dark theme. You can also reference the tokens directly: every color, type style, radius, and spacing value is a quoted value you can paste into Tailwind config, CSS variables, or your own component library."

colors:
  primary: "#000000"
  on-primary: "#ffffff"
  accent-blue: "#2b89ff"
  ink: "#ffffff"
  ink-muted: "#b2b6bd"
  ink-subtle: "#656a76"
  canvas: "#000000"
  surface-1: "#15181e"
  surface-2: "#1f232b"
  surface-3: "#3b3d45"
  hairline: "#3b3d45"
  hairline-soft: "#252830"
  inverse-canvas: "#ffffff"
  inverse-ink: "#000000"
  product-terraform: "#7b42bc"
  product-terraform-bright: "#911ced"
  product-vault: "#ffcf25"
  product-consul: "#e62b1e"
  product-waypoint: "#14c6cb"
  product-waypoint-deep: "#12b6bb"
  product-vagrant: "#1868f2"
  product-nomad: "#00ca8e"
  product-boundary: "#f24c53"
  amber-100: "#fbeabf"
  amber-200: "#bb5a00"
  blue-7: "#101a59"
  semantic-success: "#00ca8e"
  semantic-warning: "#ffcf25"
  semantic-error: "#e62b1e"
  semantic-visited: "#a737ff"

typography:
  display-xl:
    fontFamily: hashicorpSans
    fontSize: 80px
    fontWeight: 700
    lineHeight: 1.17
    letterSpacing: -2.5px
  display-lg:
    fontFamily: hashicorpSans
    fontSize: 56px
    fontWeight: 700
    lineHeight: 1.18
    letterSpacing: -1.6px
  display-md:
    fontFamily: hashicorpSans
    fontSize: 40px
    fontWeight: 600
    lineHeight: 1.19
    letterSpacing: -1.0px
  headline:
    fontFamily: hashicorpSans
    fontSize: 28px
    fontWeight: 600
    lineHeight: 1.21
    letterSpacing: -0.6px
  card-title:
    fontFamily: hashicorpSans
    fontSize: 22px
    fontWeight: 600
    lineHeight: 1.18
    letterSpacing: -0.4px
  subhead:
    fontFamily: hashicorpSans
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: -0.2px
  body-lg:
    fontFamily: hashicorpSans
    fontSize: 18px
    fontWeight: 500
    lineHeight: 1.69
    letterSpacing: 0
  body:
    fontFamily: hashicorpSans
    fontSize: 16px
    fontWeight: 500
    lineHeight: 1.50
    letterSpacing: 0
  body-sm:
    fontFamily: hashicorpSans
    fontSize: 14px
    fontWeight: 500
    lineHeight: 1.71
    letterSpacing: 0
  caption:
    fontFamily: hashicorpSans
    fontSize: 13px
    fontWeight: 500
    lineHeight: 1.38
    letterSpacing: 0.2px
  button:
    fontFamily: hashicorpSans
    fontSize: 14px
    fontWeight: 600
    lineHeight: 1.29
    letterSpacing: 0
  eyebrow:
    fontFamily: hashicorpSans
    fontSize: 12px
    fontWeight: 600
    lineHeight: 1.23
    letterSpacing: 0.6px

rounded:
  xs: 4px
  sm: 6px
  md: 8px
  lg: 12px
  xl: 16px
  xxl: 24px
  pill: 9999px
  full: 9999px

spacing:
  hair: 1px
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  xxl: 48px
  section: 96px

components:
  button-primary:
    backgroundColor: "{colors.inverse-canvas}"
    textColor: "{colors.inverse-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 10px 18px
  button-primary-pressed:
    backgroundColor: "{colors.inverse-canvas}"
    textColor: "{colors.inverse-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
  button-secondary:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 10px 18px
  button-tertiary:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 10px 18px
  button-product-terraform:
    backgroundColor: "{colors.product-terraform}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 10px 18px
  button-product-vault:
    backgroundColor: "{colors.product-vault}"
    textColor: "{colors.inverse-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 10px 18px
  button-product-waypoint:
    backgroundColor: "{colors.product-waypoint}"
    textColor: "{colors.inverse-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 10px 18px
  product-card:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 24px
  product-card-terraform:
    backgroundColor: "{colors.product-terraform}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 24px
  product-card-vault:
    backgroundColor: "{colors.product-vault}"
    textColor: "{colors.inverse-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 24px
  product-card-waypoint:
    backgroundColor: "{colors.product-waypoint}"
    textColor: "{colors.inverse-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 24px
  feature-card:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 24px
  pricing-card:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 32px
  pricing-card-featured:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 32px
  resource-card:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.lg}"
    padding: 16px
  text-input:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: 10px 14px
  text-input-focused:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: 10px 14px
  product-pill:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: 4px 10px
  top-nav:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.xs}"
    height: 64px
  comparison-row:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.xs}"
  cta-banner:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.subhead}"
    rounded: "{rounded.xxl}"
    padding: 48px
  footer:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.caption}"
    rounded: "{rounded.xs}"
    padding: 64px 32px
---

## Overview

HashiCorp's marketing canvas is a near-black ground that serves a multi-product portfolio without ever feeling generic. The dominant surface is `{colors.canvas}` (pure black) layered with `{colors.surface-1}` charcoal cards and 1px translucent gray hairlines. The chrome is monochrome — white pill-rounded buttons (`{components.button-primary}`), white type, gray secondary type — but the system is held together by a **palette of per-product accent colors** that signal which HashiCorp tool a given section belongs to: Terraform purple, Vault yellow, Consul red, Waypoint cyan, Vagrant blue, Nomad green, Boundary coral.

Display type is **hashicorpSans** at weights 600/700 with tight line-heights (1.17–1.21); body type is the same family at 500 weight with deliberately relaxed line-heights (1.50–1.71) — the contrast feels editorial, not enterprise-templated. CTAs use small `{rounded.md}` 8px corners rather than pills, which keeps the system reading as developer-facing rather than consumer-y.

The signature device is the **product-card** family — each HashiCorp product gets its own colored card variant on the home and infrastructure pages, lifting Terraform into a violet ground, Vault into yellow, Waypoint into cyan. These aren't decorative gradients — they're identity surfaces. A reader scrolling the page can tell which product a section is about from the corner of their eye.

**Key Characteristics:**
- Black-canvas marketing system: `{colors.canvas}` is the surface for hero, body, pricing, comparison tables, and footer alike.
- **Per-product color identity**: Terraform `{colors.product-terraform}`, Vault `{colors.product-vault}`, Waypoint `{colors.product-waypoint}`, Vagrant `{colors.product-vagrant}`, Consul `{colors.product-consul}`, Nomad `{colors.product-nomad}`, Boundary `{colors.product-boundary}` — each with its own button + card variant.
- Display headlines run hashicorpSans 600/700 with line-height 1.17–1.21 (tight); body runs the same family at 500 with 1.50–1.71 (relaxed) — the proportional gap is the brand's voice.
- CTA shape is `{rounded.md}` 8px — not a pill — keeping the system reading as developer-tool rather than consumer-app.
- Charcoal surface lift (canvas → surface-1 → surface-2) instead of shadow-driven elevation.
- 1px translucent gray hairlines (`rgba(178,182,189,0.1)`) define cards and dividers — the borders are felt more than seen.
- Eyebrow typography (12–13px, 600 weight, 0.6px positive tracking, uppercase) marks every section as a category label.

## Known Gaps

- The exact product-color hex values come from the `--mds-color-*` CSS variable set extracted directly; they are HashiCorp's canonical brand spec.
- Shadow tokens are not extensively documented because the dark surface system uses surface lift instead of shadow elevation.
- Form-field error and validation styling is not visible on the inspected pages.
- Dark mode is the only marketing mode — light-mode adaptation is not documented.
- Product-card variants for Consul, Nomad, Vagrant, and Boundary follow the documented Terraform / Vault / Waypoint pattern but are referenced in prose only; if they need formal entries they can be added as `product-card-consul`, `product-card-nomad`, etc.
