"""Prompts package — barrel re-exports.

Single source of truth for everything related to the agent's system prompt:

* :mod:`.builder` — main ``get_system_prompt`` and the 7 static section
  helpers + tool-name constants.
* :mod:`.sections` — memoization framework for dynamic-tail sections.
* :mod:`.api` — structural splitting + wire-format collapse for the
  resulting array.
* :mod:`.cyber_risk_instruction` — single safety constant referenced from
  the intro section.
* ``slide_generator.md`` — the slide-design contract loaded by
  ``builder.get_simple_system_section``. Edit the file in-place; changes
  pick up on process restart.

Per ``feedback_init_barrel_only`` workspace convention: this module
re-exports the public surface only — no logic, no transitive heavy
imports.
"""

from .api import (
    SystemPromptBlock,
    build_system_prompt_string,
    split_sys_prompt_prefix,
)
from .builder import (
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    get_actions_section,
    get_output_efficiency_section,
    get_simple_doing_tasks_section,
    get_simple_intro_section,
    get_simple_system_section,
    get_simple_tone_and_style_section,
    get_system_prompt,
    get_using_your_tools_section,
)
from .cyber_risk_instruction import CYBER_RISK_INSTRUCTION
from .sections import (
    DANGEROUS_uncached_system_prompt_section,
    SystemPromptSection,
    clear_system_prompt_sections,
    resolve_system_prompt_sections,
    system_prompt_section,
)

__all__ = [
    "CYBER_RISK_INSTRUCTION",
    "DANGEROUS_uncached_system_prompt_section",
    "SYSTEM_PROMPT_DYNAMIC_BOUNDARY",
    "SystemPromptBlock",
    "SystemPromptSection",
    "build_system_prompt_string",
    "clear_system_prompt_sections",
    "get_actions_section",
    "get_output_efficiency_section",
    "get_simple_doing_tasks_section",
    "get_simple_intro_section",
    "get_simple_system_section",
    "get_simple_tone_and_style_section",
    "get_system_prompt",
    "get_using_your_tools_section",
    "resolve_system_prompt_sections",
    "split_sys_prompt_prefix",
    "system_prompt_section",
]
