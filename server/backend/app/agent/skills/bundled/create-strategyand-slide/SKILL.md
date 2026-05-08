---
name: create-strategyand-slide
description: Strategy& brand recipe — palette, typography, layout principles, and voice for Strategy&-branded slides. Apply before calling CreateSlide so the deck looks on-brand.
argumentHint: "<optional: deck topic or audience>"
aliases: [strategyand, strategy-and-brand, strategy-and-style]
whenToUse: When the user asks for a Strategy&-branded deck (sometimes written "Strategy and", "Strategy&", or "S&"). Invoke once before the first CreateSlide call; the values apply to every CreateSlide call for the rest of the conversation unless the user changes brands.
---

You are creating slides in **Strategy&** brand (PwC's strategy consulting practice, formerly Booz & Company). When you call `CreateSlide` (now and for the rest of this conversation, until the user changes brands), apply the brand values described below as inline styles on each div. The structural contract — canvas dimensions, absolute positioning, inline-style requirement, allowed elements, no JavaScript — comes from `CreateSlide`'s tool description and is brand-agnostic. **This skill describes the look-and-feel only, not the structure.**

> **Note for maintainers:** the values below are a reasonable starting point and intentionally distinct from PwC corporate so the routing layer can be tested. Verify with the Strategy& brand team before production use.

## Theme

High-contrast editorial minimalism. Strategy& is more pointed and modernist than PwC corporate — fewer colours, more whitespace, sharper typography, bolder claims per slide. Think *Harvard Business Review cover* rather than *board-room deck*.

## Palette

- **Primary backgrounds**: pure black `#000000` and pure white `#FFFFFF`. Black for title and section-divider slides; white for content / body slides. No mid-tone backgrounds.
- **Signature accent**: Strategy& red `#E2231A`. Use for accent bars, dividers, the ampersand in titles, key callouts, and emphasis. Never as a background fill larger than a thin stripe.
- **Greys**: warm grey `#9C9C9C` for subtitles and secondary labels; pale grey `#F2F2F2` for occasional separators on white slides.
- **Text on black**: white `#FFFFFF` primary, warm grey `#9C9C9C` secondary.
- **Text on white**: black `#000000` primary, warm grey `#9C9C9C` secondary.
- **Strict palette**: black, white, red, grey only. No blue, green, yellow, pastels, or gradients of any kind.

## Typography

- **Body font**: Helvetica, with Arial and a generic sans as fallbacks. Helvetica is preferred — Strategy& is historically a Helvetica brand.
- **No serif.** Strategy& is sans-serif throughout — never Georgia or any serif face.
- **Sizing**: titles 36–52 px at weight 700 (bold). Section headers 22–28 px at weight 500 (medium). Body 14–18 px at weight 400 (regular). Never below 14 px.
- **Letter-spacing**: titles may use slightly negative letter-spacing (around `-0.5px`) for a tighter, more editorial feel. Body text uses default spacing.
- **Hierarchy**: very strong — titles should dominate; body sits as a quiet supporting layer.

## Layout principles

- **More whitespace than PwC corporate.** Leave the upper third of content slides empty above the title. Title slides centre vertically with deep space above and below.
- **Minimal accent decoration.** Typically a single short red bar (3–4 px tall, ~60–80 px wide — *narrower* than PwC's accent bar) below or to the left of a title. One accent per slide; never multiple.
- **Bullets without glyphs.** Don't prefix bullets with `•` by default — let typography and spacing carry the hierarchy. Vertical spacing ~32–40 px between lines (more breathing room than PwC).
- **Charts and diagrams** use the strict palette only — black or white fills, red accents, grey gridlines. No additional colours even for data-series differentiation.

## Voice and content

- Sharp, declarative, opinionated. *"The case for X"*, *"Why Y wins"* — not *"Considerations regarding Z"*.
- Lead with a single bold takeaway per slide when the format supports it.
- No marketing language, no exclamation points, no emoji.
- Bullets are short (≤ 10 words — *tighter* than PwC) and parallel.
- Numbers are precise.

After invoking this skill, proceed with the user's request — call `CreateSlide` once per slide, inlining these brand values on each div per `CreateSlide`'s structural contract.

