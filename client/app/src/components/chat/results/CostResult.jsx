import { DollarSign, ArrowDownRight, ArrowUpRight, Layers, Zap, Clock } from "lucide-react";

function Stat({ icon, label, value, accent }) {
  return (
    <div className="flex items-center gap-2 px-2.5 py-2">
      <div className={`w-6 h-6 rounded-lg flex items-center justify-center shrink-0 ${accent ? "bg-brand/10 text-brand" : "bg-gray-100 text-gray-400"}`}>
        {icon}
      </div>
      <div className="min-w-0">
        <div className={`text-[13px] font-semibold ${accent ? "text-brand" : "text-gray-700"}`}>{value}</div>
        <div className="text-[10px] text-gray-400">{label}</div>
      </div>
    </div>
  );
}

export default function CostResult({ data }) {
  if (!data) return <p className="text-[12px] text-gray-400 italic">No usage data available.</p>;
  const fmt = (n) => (n || 0).toLocaleString();
  const session = data.session || {};
  const period = data.period || {};

  return (
    <div className="space-y-3">
      {period.cost > 0 && (
        <>
          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide px-2.5">Last 30 days</div>
          <div className="grid grid-cols-2 gap-x-2">
            <Stat icon={<DollarSign size={13} />} label="Total cost" value={`$${(period.cost || 0).toFixed(4)}`} accent />
            <Stat icon={<Zap size={13} />} label="Requests" value={fmt(period.requests)} />
            <Stat icon={<ArrowDownRight size={13} />} label="Input tokens" value={fmt(period.inputTokens)} />
            <Stat icon={<ArrowUpRight size={13} />} label="Output tokens" value={fmt(period.outputTokens)} />
            <Stat icon={<Layers size={13} />} label="Total tokens" value={fmt(period.totalTokens)} />
          </div>
          {period.byModel?.length > 0 && (
            <div className="px-2.5 space-y-1">
              <div className="text-[10px] text-gray-400">By model</div>
              {period.byModel.map((m, i) => (
                <div key={i} className="flex justify-between text-[11px]">
                  <span className="text-gray-500">{m.model}</span>
                  <span className="text-gray-700 font-medium">${parseFloat(m.total_cost_usd || 0).toFixed(4)}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
      <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide px-2.5">This session</div>
      <div className="grid grid-cols-2 gap-x-2">
        <Stat icon={<Clock size={13} />} label="Requests" value={fmt(session.requests)} />
        <Stat icon={<Layers size={13} />} label="Total tokens" value={fmt(session.totalTokens)} />
        <Stat icon={<ArrowDownRight size={13} />} label="Input tokens" value={fmt(session.inputTokens)} />
        <Stat icon={<ArrowUpRight size={13} />} label="Output tokens" value={fmt(session.outputTokens)} />
      </div>
    </div>
  );
}
