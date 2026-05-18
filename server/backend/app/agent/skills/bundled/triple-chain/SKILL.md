---
name: triple-chain
description: TEST FIXTURE — wraps /chained-find to exercise three-deep skill-on-skill composition (depth 3). Not for production use.
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
Find slides about ${ARGS}. To do this, invoke the `/chained-find` skill with `args="${ARGS}"` and `intent="testing depth cap via triple-chain → chained-find → find-slides; this is the depth-3 leg"`.

Return the inner skill's output verbatim.
