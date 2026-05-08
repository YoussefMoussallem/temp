import { Cpu, ArrowDownRight, ArrowUpRight } from "lucide-react";

export default function ContextResult({ data }) {
  if (!data) return null;
  const fmt = (n) => n.toLocaleString();
  const pct = data.usagePct;

  return (
    <div>
      {/* Progress bar */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1.5">
          <div className="flex items-center gap-1.5">
            <Cpu size={12} className="text-brand" />
            <span className="text-[11px] font-semibold text-gray-600">{data.model}</span>
          </div>
          <span className={`text-[11px] font-bold ${pct > 80 ? "text-red-500" : pct > 50 ? "text-amber-500" : "text-brand"}`}>
            {pct.toFixed(1)}%
          </span>
        </div>
        <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${pct > 80 ? "bg-red-400" : pct > 50 ? "bg-amber-400" : "bg-brand"}`}
            style={{ width: `${Math.min(100, pct)}%` }}
          />
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="py-1.5">
          <div className="text-[12px] font-semibold text-gray-700">{fmt(data.contextWindow)}</div>
          <div className="text-[9px] text-gray-400 uppercase tracking-wider">Window</div>
        </div>
        <div className="py-1.5">
          <div className="text-[12px] font-semibold text-gray-700">{fmt(data.inputTokens)}</div>
          <div className="text-[9px] text-gray-400 uppercase tracking-wider">Used</div>
        </div>
        <div className="py-1.5">
          <div className="text-[12px] font-semibold text-gray-700">{fmt(data.remaining)}</div>
          <div className="text-[9px] text-gray-400 uppercase tracking-wider">Remaining</div>
        </div>
      </div>
    </div>
  );
}
