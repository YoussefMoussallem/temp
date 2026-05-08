import { useState } from "react";
import { ChevronRight, Loader2, Search, CheckCircle2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function SearchBlock({ active, query, result, index, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const label = index != null ? `Search ${index + 1}` : "Web search";

  return (
    <div className="mb-2">
      <button
        onClick={() => result && setOpen(!open)}
        className={`inline-flex items-center gap-1.5 text-[11px] italic transition-colors
          ${result ? "cursor-pointer" : "cursor-default"}
          ${active ? "text-brand" : "text-gray-400 hover:text-gray-500"}`}
      >
        {active ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={11} />}
        <Search size={11} />
        <span>{active ? `${label}...` : label}</span>
        {result && (
          <ChevronRight
            size={10}
            className={`transition-transform duration-150 ${open ? "rotate-90" : ""}`}
          />
        )}
      </button>
      {open && result && (
        <div className="mt-1 pl-4 border-l-2 border-gray-100 text-[11px] text-gray-500 leading-relaxed prose prose-xs max-w-none max-h-[200px] overflow-y-auto">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{result}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}
