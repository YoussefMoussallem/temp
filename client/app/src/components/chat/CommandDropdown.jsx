/**
 * Slash-command suggestion dropdown.
 *
 * Pure presentation — receives suggestions + selection state from
 * `useTypeahead` and renders the list. Keyboard handling lives in the
 * composer; this component only owns mouse interaction (hover-to-select,
 * click-to-apply).
 *
 * Source: src/components/CommandDropdown.tsx (Ink-stripped).
 */

import { useEffect, useRef } from "react";

export default function CommandDropdown({
  suggestions,
  selectedIdx,
  onHover,
  onPick,
}) {
  const listRef = useRef(null);

  // Keep the highlighted row in view as the user arrows through.
  useEffect(() => {
    if (!listRef.current || !suggestions.length) return;
    const item = listRef.current.children[selectedIdx];
    if (item) item.scrollIntoView({ block: "nearest" });
  }, [selectedIdx, suggestions.length]);

  if (!suggestions.length) return null;

  return (
    <div
      ref={listRef}
      className="absolute bottom-full left-4 right-4 mb-1 max-h-[200px] overflow-y-auto
                 bg-white border border-gray-100 rounded-xl shadow-lg shadow-black/5 z-10 py-1"
    >
      {suggestions.map((s, i) => {
        const name = s.label;
        const isSelected = i === selectedIdx;
        return (
          <button
            key={`${name}-${i}`}
            onMouseDown={(e) => {
              // mousedown (not click) so the textarea doesn't blur first.
              e.preventDefault();
              onPick(i);
            }}
            onMouseEnter={() => onHover(i)}
            className={`w-full text-left px-3.5 py-2 flex items-baseline gap-2.5 transition-colors duration-100 cursor-pointer
              ${isSelected ? "bg-gray-50" : ""}`}
          >
            <span
              className={`text-[12px] font-semibold font-mono ${
                isSelected ? "text-brand" : "text-gray-600"
              }`}
            >
              /{name}
            </span>
            <span className="text-[11px] text-gray-400 truncate">
              {s.description}
            </span>
          </button>
        );
      })}
    </div>
  );
}
