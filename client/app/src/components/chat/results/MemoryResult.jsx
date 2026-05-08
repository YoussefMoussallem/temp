import { BookOpen, Trash2 } from "lucide-react";

export default function MemoryResult({ data }) {
  if (data.cleared) {
    return (
      <div className="flex items-center gap-2 text-[12px] text-gray-500">
        <Trash2 size={12} />
        <span>All memories cleared.</span>
      </div>
    );
  }

  if (data.memories.length === 0) {
    return (
      <div className="text-[12px] text-gray-400 italic">
        No saved memories. Use <span className="font-mono font-semibold text-gray-500">/remember</span> to save one.
      </div>
    );
  }

  return (
    <div>
      {data.filter && (
        <div className="text-[10px] text-gray-400 mb-2">
          Showing {data.memories.length} of {data.total} matching "{data.filter}"
        </div>
      )}
      <div className="flex flex-col gap-1.5">
        {data.memories.map((mem, i) => (
          <div key={i} className="flex items-start gap-2 px-2.5 py-1.5 rounded-lg hover:bg-white/60 transition-colors">
            <BookOpen size={11} className="text-brand mt-0.5 shrink-0" />
            <div className="min-w-0">
              <div className="text-[12px] text-gray-700">{mem.text}</div>
              <div className="text-[9px] text-gray-400">{new Date(mem.date).toLocaleDateString()}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
