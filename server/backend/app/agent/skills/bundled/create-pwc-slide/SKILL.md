---
name: create-pwc-slide
description: PwC brand recipe — palette, typography, layout principles, and voice for PwC-branded slides. Apply before calling CreateSlide so the deck looks on-brand.
argumentHint: "<optional: deck topic or audience>"
aliases: [pwc-brand, pwc-style]
whenToUse: When the user asks for a PwC-branded deck, or when no brand is named and PwC is the default for this deployment. Invoke once before the first CreateSlide call; the values apply to every CreateSlide call for the rest of the conversation unless the user changes brands.
---

You are creating slides in **PwC** brand. When you call `CreateSlide` (now and for the rest of this conversation, until the user changes brands), apply the brand values described below as inline styles on each div. The structural contract — canvas dimensions, absolute positioning, inline-style requirement, allowed elements, no JavaScript — comes from `CreateSlide`'s tool description and is brand-agnostic. **This skill describes the look-and-feel only, not the structure.**

## Theme

PwC corporate: institutional, consulting-grade, restrained. Strong visual hierarchy with generous whitespace; never busy or decorative. The deck should feel like a board-room deliverable — measured, neutral, and professional.

## Palette

- **Primary backgrounds**: dark navy `#1B2A4A` and white `#FFFFFF`. Use navy for title and section-divider slides; white for body and content slides.
- **Accents**: PwC burgundy `#9B1B30` (primary accent) and warm gold `#A08040` (secondary). Use sparingly — short accent bars beneath titles, thin dividers, a single highlight callout per slide. Never as large background fills.
- **Text on navy**: white `#FFFFFF` for primary, light grey `#CCCCCC` for subtitles and metadata.
- **Text on white**: navy `#1B2A4A` (or near-black `#222222`) for primary, mid-grey `#666666` for subtitles and metadata.
- **Avoid**: bright or saturated colours (no pure red, pure blue, neon, pastel) unless the user explicitly requests them. No gradients beyond a subtle 2-stop linear gradient if truly needed.

## Typography

- **Body font**: Arial, with Helvetica and a generic sans as fallbacks.
- **Optional serif for headings**: Georgia, with Times New Roman and a generic serif as fallbacks. Use a serif only when an editorial tone is desired; default is sans throughout.
- **Sizing**: titles 32–48 px at weight 700 (bold). Section headers 22–28 px at weight 600 (semibold). Body text 14–18 px at weight 400 (regular). Never below 14 px.
- **Hierarchy**: titles should dominate visually; body text reads as supporting and secondary. Don't mix weights mid-sentence.

## Layout principles

- **Generous whitespace.** Leave breathing room above titles. Content slides typically place the title near the top with the title baseline ~60 px from the top edge; title slides centre vertically with deep space above and below.
- **Consistent left margin.** Left-align body content along a single left margin (around ~60 px from the canvas left edge). Don't centre body text on content slides.
- **Title decoration.** A single short burgundy accent bar (3–4 px tall, ~80–200 px wide) immediately below a title is the canonical decoration. One per slide.
- **Bullets** are individual lines, vertically spaced ~28–36 px apart, each starting with a `•` glyph followed by a short parallel phrase.
- **Charts and diagrams** use the brand palette only — navy fills, burgundy/gold accents, mid-grey gridlines. No additional data-series colours.

## Voice and content

- Consulting-grade: concise, neutral, executive. No marketing language, no exclamation points, no emoji.
- Bullets are short (≤ 12 words) and parallel — all noun phrases or all action phrases per slide.
- Numbers are precise (`+18%`, `Q4 2026`, `$2.4 B`); round only when the source warrants it.
- Lead with the takeaway when the slide format supports it.

After invoking this skill, proceed with the user's request — call `CreateSlide` once per slide, inlining these brand values on each div per `CreateSlide`'s structural contract.

User's deck context (if provided): ${ARGS}
