export default function StatsCard({ icon, label, value, loading }) {
  return (
    <div className="rounded-xl bg-white border border-gray-100 shadow-sm p-4 flex items-start gap-3">
      <div className="w-8 h-8 rounded-lg bg-brand/10 text-brand flex items-center justify-center shrink-0 mt-0.5">
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 mb-1">
          {label}
        </p>
        {loading ? (
          <div className="h-5 w-16 rounded bg-gray-100 animate-pulse" />
        ) : (
          <p className="text-[18px] font-bold font-[var(--font-heading)] text-black leading-none">
            {value}
          </p>
        )}
      </div>
    </div>
  );
}
