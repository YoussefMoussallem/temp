import { useState } from "react";
import { ChevronRight, Brain, Loader2 } from "lucide-react";

export default function ThinkingBlock({ text, done = false }) {
  const [open, setOpen] = useState(!done);

  return (
    <div className="mb-2">
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1.5 text-[11px] text-gray-400 italic
                   cursor-pointer select-none hover:text-gray-500 transition-colors"
      >
        {done ? <Brain size={11} /> : <Loader2 size={11} className="animate-spin" />}
        <span>{done ? "Thought process" : "Thinking..."}</span>
        <ChevronRight
          size={10}
          className={`transition-transform duration-150 ${open ? "rotate-90" : ""}`}
        />
      </button>
      {open && (
        <div className="mt-1 pl-4 border-l-2 border-gray-100 text-[11px] text-gray-400 leading-relaxed whitespace-pre-wrap max-h-[150px] overflow-y-auto">
          {text}
        </div>
      )}
    </div>
  );
}
