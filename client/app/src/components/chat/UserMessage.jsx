import UserCommandMessage, { parseCommandExpansion } from "./UserCommandMessage.jsx";

function isSlashText(content) {
  if (typeof content !== "string") return null;
  const trimmed = content.trimStart();
  if (!trimmed.startsWith("/")) return null;
  const head = trimmed.slice(1);
  const m = head.match(/^(\S+)(?:\s+(.*))?$/);
  if (!m) return null;
  return { name: m[1], args: (m[2] || "").trim() };
}

export default function UserMessage({ content, commandUuid, commandState, raw }) {
  // Prefer the backend-expanded block list when present — the chip renderer
  // only shows the command name/args.
  const expansion = parseCommandExpansion(raw?.content ?? content);
  if (expansion) {
    return (
      <div className="my-4">
        <UserCommandMessage content={raw?.content ?? content} />
        {commandUuid ? <CommandStateTag state={commandState} /> : null}
      </div>
    );
  }

  // Still-typed slash text that hasn't been expanded yet — render as chip too.
  const typed = commandUuid ? isSlashText(content) : null;
  if (typed) {
    return (
      <div className="my-4 flex items-center gap-2">
        <div className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-2.5 py-1 text-[12px] text-gray-700">
          <span className="font-mono text-gray-900">/{typed.name}</span>
          {typed.args ? <span className="text-gray-400">·</span> : null}
          {typed.args ? <span className="truncate">{typed.args}</span> : null}
        </div>
        <CommandStateTag state={commandState} />
      </div>
    );
  }

  return (
    <div className="my-4 bg-gray-50 rounded-2xl px-4 py-3 text-[13px] leading-relaxed text-gray-800 whitespace-pre-wrap break-words">
      {content}
    </div>
  );
}

function CommandStateTag({ state }) {
  if (!state || state === "pending") return null;
  const label = state === "started" ? "running" : state === "completed" ? "done" : state;
  const color = state === "completed" ? "text-green-600" : "text-gray-400";
  return <span className={`text-[11px] ${color}`}>{label}</span>;
}
