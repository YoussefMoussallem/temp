"""
WebFetchTool prompt + name constants.

Port of src/tools/WebFetchTool/prompt.ts.

NOTE — v1 simplification (vs. source):
The source pipes fetched markdown through a small/fast LLM (Haiku) with a
secondary prompt to extract a concise summary, keeping the main loop's
context lean. v1 returns raw markdown directly (truncated at MAX bytes);
the main model handles extraction itself. Phase 5 wires the secondary-model
extraction.
"""

WEB_FETCH_TOOL_NAME = "WebFetch"

DESCRIPTION = """
- Fetches content from a specified URL and returns it as text/markdown
- Takes a URL and a prompt as input (prompt describes what info to extract)
- Fetches the URL content, converts HTML to text
- Use this tool when you need to retrieve and analyze web content

Usage notes:
  - IMPORTANT: If an MCP-provided web fetch tool is available, prefer using that tool instead of this one, as it may have fewer restrictions.
  - The URL must be a fully-formed valid URL
  - HTTP URLs will be automatically upgraded to HTTPS
  - The prompt should describe what information you want to extract from the page
  - This tool is read-only and does not modify any files
  - Results are truncated if the content is very large
  - For GitHub URLs, prefer using the gh CLI via Bash instead (e.g., gh pr view, gh issue view, gh api).
"""


def make_secondary_model_prompt(
    markdown_content: str,
    prompt: str,
    is_preapproved_domain: bool,
) -> str:
    """
    Wrap fetched markdown + user prompt for the secondary extraction model.

    Phase 5 will actually call this prompt against a small model. v1 keeps
    the function for parity but doesn't invoke a secondary model.
    """
    if is_preapproved_domain:
        guidelines = (
            "Provide a concise response based on the content above. "
            "Include relevant details, code examples, and documentation excerpts as needed."
        )
    else:
        guidelines = (
            "Provide a concise response based only on the content above. In your response:\n"
            " - Enforce a strict 125-character maximum for quotes from any source document.\n"
            "   Open Source Software is ok as long as we respect the license.\n"
            " - Use quotation marks for exact language from articles; any language outside\n"
            "   of the quotation should never be word-for-word the same.\n"
            " - You are not a lawyer and never comment on the legality of your own prompts and responses.\n"
            " - Never produce or reproduce exact song lyrics."
        )

    return f"""
Web page content:
---
{markdown_content}
---

{prompt}

{guidelines}
"""
