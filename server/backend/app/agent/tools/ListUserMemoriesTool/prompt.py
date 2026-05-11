LIST_USER_MEMORIES_TOOL_NAME = "ListUserMemories"

# The "when to call" guidance is the lever for whether the model
# actually uses memory. Specific, action-oriented triggers beat
# abstract "consider calling when relevant" framing.
DESCRIPTION = (
    "Return the index of long-term memories saved about THIS USER across "
    "all their conversations — role, working preferences, brand defaults, "
    "feedback patterns from past corrections. The result is the index "
    "only: each entry's `slug`, `type`, `name`, and one-line "
    "`description`. Use `ReadMemory(scope=\"user\", slug=...)` to fetch a "
    "specific entry's full body when its description suggests relevance.\n\n"
    "## When to call\n\n"
    "  - Starting an open-ended request where user preferences would "
    "shape the answer (tone, format, length, default brand).\n"
    "  - Before any stylistic decision the user may have a known stance "
    "on (use of emoji, hedging, summary length, jargon).\n"
    "  - When the user references their own past behaviour (\"usually I "
    "want…\", \"remember when…\", \"like the last one\").\n"
    "  - At the start of a brand-new conversation if the request isn't "
    "purely mechanical.\n\n"
    "## When not to call\n\n"
    "  - Purely mechanical tool work where preferences don't apply "
    "(\"delete slide 3\", \"swap slides 2 and 4\").\n"
    "  - More than once per turn — once you've seen the index, you have "
    "it.\n\n"
    "Calling this is cheap (one query, just the index) but skipping it "
    "when the user does have relevant preferences means re-learning the "
    "same thing every session. Bias slightly toward calling."
)
