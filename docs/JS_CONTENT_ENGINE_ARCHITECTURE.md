# JS Content Video Engine — Architecture v1

This fork keeps MoneyPrinterTurbo as the rendering/production core while adding a separate JS Content intelligence layer.

## Design goals

1. Preserve upstream compatibility and keep `main` clean.
2. Keep JS-specific logic isolated from upstream services.
3. Support brand-aware Thai content generation.
4. Add storyboard-first generation before rendering.
5. Prepare product-to-video, news-to-video, affiliate-video and social publishing workflows.
6. Avoid hard coupling to any single LLM/TTS/video provider.

## Branch strategy

- `main`: upstream-compatible fork branch.
- `develop/js-content-engine`: integration branch for JS-specific work.
- `feature/*`: isolated feature branches merged into develop through pull requests.

## Target architecture

```text
Input / Campaign Brief
        |
        v
JS Content Brain
  - Brand Profile
  - Thai Content Strategy
  - Hook / CTA
  - Script Planning
        |
        v
Storyboard Engine
  - Scene decomposition
  - Visual direction
  - Voice line
  - On-screen text
  - Duration / transition
        |
        v
MoneyPrinterTurbo Core
  - LLM providers
  - Media / AI media
  - TTS
  - BGM
  - Subtitle
  - Video renderer
        |
        v
Publisher / Analytics
  - TikTok
  - Reels
  - Shorts
  - Facebook
  - Future analytics feedback loop
```

## Phase 1 — Content Core

- BrandProfile model
- ContentBrief model
- Storyboard / Scene model
- Brand registry
- Deterministic storyboard scaffolding
- Unit-testable service boundary

## Phase 2 — AI Planning

- LLM adapter that consumes existing MoneyPrinterTurbo LLM provider layer
- Thai prompt packs
- Hook generator
- CTA generator
- Storyboard JSON generation + validation

## Phase 3 — Product / Affiliate workflows

- Product-to-video
- Shopee affiliate input normalization
- Product image / title / price / benefits extraction
- Conversion-focused script templates

## Phase 4 — News / IT Content

- Research source ingestion
- Fact/citation metadata
- News-to-short-video workflow
- JSTech-specific IT content presets

## Phase 5 — Brand OS / Multi-brand

- JSTech
- JSFLIX
- JSPLUS
- reusable customer brand profiles
- per-brand voice, visual, CTA and watermark rules

## Phase 6 — Production hardening

- Auth boundary review
- file-path / download security review
- task isolation
- rate limits
- secrets management
- deployment profiles for local, VPS and GPU workers

## Upstream policy

Do not rewrite large upstream files when extension points can be used. Prefer additive modules under `app/services/js_content/` and thin integration adapters. This keeps future upstream merges smaller and reviewable.
