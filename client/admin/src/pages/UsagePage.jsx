import DataTable from "../components/DataTable";
import { useAdminApi } from "../hooks/useAdminApi";

const COLS = [
  { key: "email", label: "User" },
  { key: "model", label: "Model" },
  {
    key: "input_tokens",
    label: "In Tokens",
    align: "right",
    render: (v) => (v != null ? Number(v).toLocaleString() : "\u2014"),
  },
  {
    key: "output_tokens",
    label: "Out Tokens",
    align: "right",
    render: (v) => (v != null ? Number(v).toLocaleString() : "\u2014"),
  },
  {
    key: "cost_usd",
    label: "Cost",
    align: "right",
    render: (v) => (v != null ? `$${Number(v).toFixed(4)}` : "\u2014"),
  },
  {
    key: "recorded_at",
    label: "Time",
    render: (v) => (v ? new Date(v).toLocaleString() : "\u2014"),
  },
];

export default function UsagePage() {
  const { data, loading, error } = useAdminApi("/api/admin/usage");
  const records = data?.records ?? [];

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-[10px] font-semibold uppercase tracking-widest text-gray-400">
          Usage Records
        </h2>
        {records.length > 0 && (
          <span className="text-brand bg-brand-dim px-1.5 py-0.5 rounded-full text-[10px] font-bold">
            {records.length}
          </span>
        )}
      </div>
      <DataTable columns={COLS} rows={records} loading={loading} error={error} emptyMessage="No usage records for this period." />
    </div>
  );
}
