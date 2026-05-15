SAVE_PROJECT_MEMORY_TOOL_NAME = "SaveProjectMemory"

DESCRIPTION = (
    "Save a long-term memory about THIS PROJECT — audience, deadline, "
    "key message, decisions made for this deck, stakeholders, external "
    "references. Loaded only inside this project's conversations. Use "
    "for facts that are specific to this deck and wouldn't carry to a "
    "different project.\n\n"
    "Requires an active project — fails otherwise.\n\n"
    "## Workflow — follow IN ORDER\n\n"
    "  1. **Confirm scope with the user.** Unless the user's last "
    'message explicitly tied the fact to this project ("for this '
    'deck", "in this project", "the audience is…", "deadline is…"), '
    "call `AskUserQuestion` first to confirm whether to save here or "
    "to `SaveUserMemory`. Memory writes are stateful — never assume "
    "scope.\n"
    "  2. **Call `ListProjectMemories`** to see existing slugs. If an "
    "entry on the same topic already exists, REUSE its slug — never "
    "create a sibling that contradicts it.\n"
    "  3. **Save** with the chosen slug, type, name, description, body.\n\n"
    "## When to save\n\n"
    "  - You learn this deck's audience, deadline, key message, "
    'stakeholder voice, or constraints → `type="project"` (or '
    "`decision` / `stakeholder` for finer categories).\n"
    "  - User makes a decision specific to this deck (chosen brand for "
    "this project, agreed narrative angle, slide-count target) → "
    '`type="decision"`.\n'
    "  - You learn who the audience is or who's reviewing the deck → "
    '`type="stakeholder"`.\n'
    "  - User references an external resource specific to this project "
    '(client brand book URL, source data file) → `type="reference"`.\n\n'
    "## What NOT to save here\n\n"
    "  - The user's cross-project preferences (general feedback "
    "patterns, default brand, role). Those belong in `SaveUserMemory`.\n"
    "  - Slide content, recent tool results, or current todos.\n"
    "  - One-off corrections that won't apply to future turns in this "
    "project.\n\n"
    "## Conflict resolution\n\n"
    "  - **Decision changed** (\"actually let's go with audience X "
    'instead of Y") → re-save with the SAME slug. Body captures the '
    "current decision only.\n"
    "  - **Refined / clarified** → re-save with the same slug.\n"
    '  - **Retracted** ("forget that — we\'re not doing X anymore") → '
    "call `DeleteMemory` instead.\n"
    "  - **NEVER** create a sibling slug that contradicts an existing "
    "entry.\n\n"
    "## Field rules\n\n"
    "  - `slug`: `[a-z0-9_]+`, ≤64 chars. Examples: `audience`, "
    "`deadline`, `key_message`, `stakeholder_primary`, "
    "`reference_brand_book`.\n"
    "  - `type`: one of `project` / `reference` / `stakeholder` / "
    "`decision`.\n"
    "  - `name`: human-readable title, ≤120 chars.\n"
    "  - `description`: one-line hook for the index, ≤150 chars.\n"
    "  - `body`: full markdown. For decisions, include the rationale "
    "and date so future-you knows whether it's still load-bearing."
)
