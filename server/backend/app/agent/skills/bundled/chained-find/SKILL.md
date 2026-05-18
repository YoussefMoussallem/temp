---
name: chained-find
description: TEST FIXTURE — wraps /find-slides to exercise skill-on-skill composition (depth 2). Not for production use.
argumentHint: <topic to search for>
whenToUse: Manual testing only. Don't include in user-facing skill listings.
isHidden: true
fork: true
agent: Explore
allowedTools:
  - Skill
  - ListSlides
  - ReadSlide
---
Find slides about ${ARGS}. To do this, invoke the `/find-slides` skill with `args="${ARGS}"` and `intent="composing find-slides via chained-find for testing depth=2 skill-on-skill recursion"`.

Return the inner skill's output verbatim.
