---
name: find-slides
description: Read-only slide search — return slides matching a topic, with slide numbers and a one-line excerpt each.
argumentHint: <topic to search for>
whenToUse: When the user wants to locate slides about a specific topic.
fork: true
agent: Explore
allowedTools:
  - ListSlides
  - ReadSlide
systemPromptOverlay: |
  When reporting findings, always lead each result with the slide number
  in `[Slide N]` format, followed by a short excerpt. Sort by slide order.
---
Search the current deck for slides matching: ${ARGS}

1. Call `ListSlides` once to get the deck inventory.
2. For each plausibly-relevant slide, call `ReadSlide` to confirm.
3. Return a numbered list of matches in slide order. Format each line as:
   `[Slide N] short excerpt explaining the match`
4. If nothing matches, say "No slides match: ${ARGS}" — do not invent results.

Be concise. No preamble; jump straight to the list.
