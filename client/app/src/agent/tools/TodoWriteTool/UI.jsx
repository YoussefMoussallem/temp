import { useState } from "react";
import { ListChecks, Circle, Loader2, CheckCircle2, ChevronDown, ChevronRight } from "lucide-react";

const STATUS_ICON = {
  pending: <Circle size={11} className="text-gray-300" />,
  in_progress: <Loader2 size={11} className="animate-spin text-amber-500" />,
  completed: <CheckCircle2 size={11} className="text-green-500" />,
};

export default function TodoWriteUI({ todos }) {
  const [open, setOpen] = useState(true);

  if (!todos || todos.length === 0) return null;

  const completed = todos.filter((t) => t.status === "completed").length;

  return (
    <div className="py-1.5 px-1">
      <div className="rounded-xl border border-amber-200/50 bg-amber-50/20 overflow-hidden">
        <button
          onClick={() => setOpen((o) => !o)}
          className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-amber-50/40 transition-colors cursor-pointer"
        >
          <ListChecks size={12} className="text-amber-600" />
          <span className="text-[11px] font-semibold text-amber-800 flex-1">
            Plan Steps
          </span>
          <span className="text-[10px] text-amber-600/70">
            {completed}/{todos.length}
          </span>
          {open
            ? <ChevronDown size={12} className="text-amber-500" />
            : <ChevronRight size={12} className="text-amber-500" />
          }
        </button>

        {open && (
          <div className="px-3 pb-2.5 space-y-1">
            {todos.map((todo) => (
              <div key={todo.id} className="flex items-start gap-2">
                <div className="mt-0.5 flex-shrink-0">
                  {STATUS_ICON[todo.status] || STATUS_ICON.pending}
                </div>
                <span className={`text-[11px] leading-snug ${
                  todo.status === "completed" ? "text-gray-400 line-through" : "text-gray-700"
                }`}>
                  {todo.subject}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
