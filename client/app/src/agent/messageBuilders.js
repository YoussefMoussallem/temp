// Translate a db-service message row to the UI's message shape. Assistant
// rows store blocks (text + tool_use); the UI wants a single string content
// for rendering, so we concat the text blocks. The full blocks are kept in
// meta.raw for code paths that need the structured form.
//
// Compact-boundary rows (system role + content[0].type === "compact_boundary")
// produced by /compact or autoCompact are recognised and rewritten to the
// {role: "compact-boundary", boundary} shape that <Message> dispatches to
// the <CompactBoundary> divider component — same shape the SSE handler
// uses for in-session events, so the divider renders identically whether
// the boundary is fresh or loaded from history.

export function rowToUiMessage(row) {
  const content = row.content;
  if (row.role === "assistant") {
    const blocks = Array.isArray(content) ? content : [];
    const text = blocks
      .filter((b) => b?.type === "text")
      .map((b) => b.text || "")
      .join("");
    return { role: "assistant", content: text, meta: { raw: blocks } };
  }
  if (row.role === "user") {
    if (typeof content === "string") return { role: "user", content };
    const blocks = Array.isArray(content) ? content : [];
    const text = blocks
      .filter((b) => b?.type === "text")
      .map((b) => b.text || "")
      .join("");
    if (text) return { role: "user", content: text };
    // Tool-result-only user message — not displayed directly; kept out of UI.
    return null;
  }
  if (row.role === "system" && Array.isArray(content) && content[0]?.type === "compact_boundary") {
    // Persisted compaction boundary. Strip the "type" tag from the
    // payload — CompactBoundary.jsx reads tokens_before/after, summary,
    // dropped_count, manual, compacted_at directly off the prop.
    const { type: _omit, ...boundary } = content[0];
    return { role: "compact-boundary", boundary };
  }
  return { role: row.role, content: typeof content === "string" ? content : "" };
}
