"""Constants package — barrel re-exports only.

Per ``feedback_init_barrel_only`` workspace convention: this module
re-exports the public surface of the constants subpackage. No logic, no
transitive heavy imports.

Note: prompt-related constants (``CYBER_RISK_INSTRUCTION``, the section
helpers, ``SYSTEM_PROMPT_DYNAMIC_BOUNDARY``, etc.) live in
:mod:`agent.prompts`. This package now only owns the ``xml`` tag constants
used by slash-command rendering and bash-tool output wrapping.
"""

from .xml import (
    BASH_INPUT_TAG,
    BASH_STDERR_TAG,
    BASH_STDOUT_TAG,
    COMMAND_ARGS_TAG,
    COMMAND_MESSAGE_TAG,
    COMMAND_NAME_TAG,
    LOCAL_COMMAND_CAVEAT_TAG,
    LOCAL_COMMAND_STDERR_TAG,
    LOCAL_COMMAND_STDOUT_TAG,
    TERMINAL_OUTPUT_TAGS,
)

__all__ = [
    "BASH_INPUT_TAG",
    "BASH_STDERR_TAG",
    "BASH_STDOUT_TAG",
    "COMMAND_ARGS_TAG",
    "COMMAND_MESSAGE_TAG",
    "COMMAND_NAME_TAG",
    "LOCAL_COMMAND_CAVEAT_TAG",
    "LOCAL_COMMAND_STDERR_TAG",
    "LOCAL_COMMAND_STDOUT_TAG",
    "TERMINAL_OUTPUT_TAGS",
]
