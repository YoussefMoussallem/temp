# Slide Brand Routing

Slide tools (`CreateSlide`, `UpdateSlide`) need **brand values** — palette, typography, layout, voice — in context before they fire. Those values come from a brand-recipe **skill** you invoke via the `Skill` tool. The structural contract (canvas, positioning, inline styles, etc.) is brand-agnostic and lives in `CreateSlide`'s tool description; don't duplicate it.

Find brand recipes in the **Available skills** inventory by matching their `description`, which always starts with the brand name (e.g. *"PwC brand recipe — …"*, *"Strategy& brand recipe — …"*). Skill `name` fields are free-form — match on description, not name.

## Routing

Invoke a recipe before the **first `CreateSlide` / `UpdateSlide` call** of the conversation, and again whenever the brand changes:

1. **User names a brand** (*"PwC deck"*, *"Strategy& pitch"*, *"Acme deck"*) → load that brand's recipe. If no matching recipe is registered, say so and proceed with neutral defaults.
2. **No brand named** → load the **PwC** recipe as this deployment's default. User can override anytime.
3. **Brand change mid-conversation** (*"redo this in Strategy&"*) → load the new recipe before the next slide-tool call. Don't carry over the previous brand's values.

Once loaded, a recipe stays in effect for every subsequent slide-tool call until the user changes brands — don't re-invoke it per call. Never combine recipes in one deck; they set conflicting values for the same fields.

Non-slide turns (chat, plan-mode outlines, `outline-deck`, etc.) don't need a recipe.
