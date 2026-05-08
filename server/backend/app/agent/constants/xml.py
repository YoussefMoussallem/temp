"""
XML tag constants used across commands + bash/terminal output.

Port of src/constants/xml.ts.
"""

# Slash-command wrapping tags.
COMMAND_NAME_TAG = "command-name"
COMMAND_MESSAGE_TAG = "command-message"
COMMAND_ARGS_TAG = "command-args"

# Bash tool output tags.
BASH_INPUT_TAG = "bash-input"
BASH_STDOUT_TAG = "bash-stdout"
BASH_STDERR_TAG = "bash-stderr"

# Local command output tags (used to wrap stdout/stderr/caveat from LocalCommand.call()).
LOCAL_COMMAND_STDOUT_TAG = "local-command-stdout"
LOCAL_COMMAND_STDERR_TAG = "local-command-stderr"
LOCAL_COMMAND_CAVEAT_TAG = "local-command-caveat"

# Tuple of every tag that represents terminal-like output — used by rendering
# layers to decide what to wrap in a monospaced pre-block.
TERMINAL_OUTPUT_TAGS: tuple[str, ...] = (
    BASH_INPUT_TAG,
    BASH_STDOUT_TAG,
    BASH_STDERR_TAG,
    LOCAL_COMMAND_STDOUT_TAG,
    LOCAL_COMMAND_STDERR_TAG,
    LOCAL_COMMAND_CAVEAT_TAG,
)
