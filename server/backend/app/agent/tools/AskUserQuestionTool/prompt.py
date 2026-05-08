ASK_USER_QUESTION_TOOL_NAME = "AskUserQuestion"

DESCRIPTION = """
Ask the user a clarifying multiple-choice question. The frontend renders a
modal; the user picks an option (or types a free-text answer); their
selection is returned as the tool result on the next turn.

When to use:
  - The request is genuinely ambiguous and the choice would change your
    output materially.
  - You're about to take an irreversible or expensive action and need
    explicit confirmation.
  - Only the user can answer — preferences, scope, audience, format, tone,
    identity, or any decision that depends on information you don't have.

When NOT to use:
  - A sensible default exists — pick it and proceed.
  - The answer is already in the conversation or in available context.
  - The question is rhetorical or just an acknowledgement of the request.

Mechanics:
  - 1-4 questions per call.
  - Each question must have 2-4 options. An "Other" free-text option is
    appended automatically by the UI; do not add your own.
  - Set multiSelect: true when choices are not mutually exclusive.
  - `header` is a short chip label shown next to the question (max 12 chars).
  - Optional `preview` on an option holds short illustrative content (sample
    text, sketch, snippet, fragment, layout outline, etc.) to help the user
    compare options visually. Keep it brief — it's a comparison aid, not a
    full artifact.
"""
