import { useRef, useCallback, useState } from "react";
import { ArrowUp, Square } from "lucide-react";
import { useTypeahead } from "../../hooks/useTypeahead.js";
import CommandDropdown from "./CommandDropdown.jsx";

export default function InputArea({ disabled, onSend, onStop }) {
  const ref = useRef(null);
  const [text, setText] = useState("");
  const [cursor, setCursor] = useState(0);

  // Slash typeahead — Fuse-backed, handles mid-input slashes, hidden
  // commands filtered, prefix-empty case returns alphabetized list.
  const onValueChange = useCallback((next, nextCursor) => {
    if (!ref.current) return;
    ref.current.value = next;
    setText(next);
    requestAnimationFrame(() => {
      if (!ref.current) return;
      ref.current.focus();
      try {
        ref.current.setSelectionRange(nextCursor, nextCursor);
      } catch {
        /* IE-style fallback not needed in evergreen browsers */
      }
      setCursor(nextCursor);
    });
  }, []);

  const {
    suggestions,
    selectedIdx,
    setSelectedIdx,
    moveSelection,
    applySelected,
    applyAt,
  } = useTypeahead({
    value: text,
    cursorOffset: cursor,
    onValueChange,
    disabled,
  });

  const handleSend = useCallback(() => {
    if (!ref.current) return;
    const val = ref.current.value.trim();
    if (!val || disabled) return;
    onSend(val);
    ref.current.value = "";
    ref.current.style.height = "auto";
    setText("");
    setCursor(0);
  }, [disabled, onSend]);

  const handleKey = useCallback(
    (e) => {
      if (suggestions.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          moveSelection(1);
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          moveSelection(-1);
          return;
        }
        if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
          // Completes the highlighted suggestion. The typeahead helper
          // appends a trailing space, which causes
          // ``findMidInputSlashCommand`` to return null on the next
          // render — suggestions become empty, and the next Enter
          // falls through to ``handleSend`` below.
          e.preventDefault();
          applySelected();
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          if (ref.current) {
            ref.current.value = "";
            setText("");
            setCursor(0);
          }
          return;
        }
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend, suggestions.length, moveSelection, applySelected],
  );

  const handleInput = useCallback(() => {
    if (!ref.current) return;
    ref.current.style.height = "auto";
    ref.current.style.height = Math.min(ref.current.scrollHeight, 120) + "px";
    setText(ref.current.value);
    setCursor(ref.current.selectionStart ?? ref.current.value.length);
  }, []);

  const handleSelect = useCallback(() => {
    if (!ref.current) return;
    setCursor(ref.current.selectionStart ?? ref.current.value.length);
  }, []);

  return (
    <div className="relative px-4 pb-4 pt-2 shrink-0">
      <CommandDropdown
        suggestions={suggestions}
        selectedIdx={selectedIdx}
        onHover={setSelectedIdx}
        onPick={applyAt}
      />

      <div className="flex items-end gap-2 rounded-xl border border-gray-200/70 bg-white px-3.5 py-2
                      focus-within:border-gray-300 transition-colors duration-150">
        <textarea
          ref={ref}
          rows={1}
          placeholder="Message Edwin..."
          onKeyDown={handleKey}
          onInput={handleInput}
          onSelect={handleSelect}
          onClick={handleSelect}
          className="flex-1 resize-none bg-transparent min-h-[32px] max-h-[120px] text-[13px] leading-relaxed
                     outline-none placeholder:text-gray-400 py-0.5"
        />
        {disabled ? (
          <button
            onClick={onStop}
            className="w-7 h-7 rounded-lg bg-brand text-white flex items-center justify-center
                       cursor-pointer transition-colors hover:bg-brand-light shrink-0"
          >
            <Square size={10} fill="currentColor" />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!text.trim()}
            className="w-7 h-7 rounded-lg bg-black text-white flex items-center justify-center
                       cursor-pointer transition-colors hover:bg-gray-800
                       disabled:bg-gray-100 disabled:text-gray-300 disabled:cursor-default shrink-0"
          >
            <ArrowUp size={14} strokeWidth={2.5} />
          </button>
        )}
      </div>
    </div>
  );
}
