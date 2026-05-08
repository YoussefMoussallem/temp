"""
WebSearchTool prompt + name constants.
"""

WEB_SEARCH_TOOL_NAME = "WebSearch"

DESCRIPTION = """
Search the web for current information using a search model.

Only use this tool when the user's question requires up-to-date facts,
real-time data, or information you are not confident about.

Do NOT search for:
  - Greetings or casual conversation
  - Questions you can answer confidently from your training data
  - Simple factual questions that don't require recent information

Usage notes:
  - Provide a clear, specific search query
  - The search is performed by a secondary model with web access
  - Results are returned as synthesized text, not raw search links
"""
