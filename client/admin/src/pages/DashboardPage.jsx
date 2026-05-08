import { Users, Activity, Cpu, DollarSign } from "lucide-react";
import StatsCard from "../components/StatsCard";
import DataTable from "../components/DataTable";
import { useAdminApi } from "../hooks/useAdminApi";

const USER_COLS = [
  { key: "email", label: "User" },
  { key: "display_name", label: "Name" },
  { key: "record_count", label: "Requests", align: "right" },
  {
    key: "total_input_tokens",
    label: "Input Tokens",
    align: "right",
    render: (v) => (v != null ? Number(v).toLocaleString() : "\u2014"),
  },
  {
    key: "total_output_tokens",
    label: "Output Tokens",
    align: "right",
    render: (v) => (v != null ? Number(v).toLocaleString() : "\u2014"),
  },
  {
    key: "total_cost_usd",
    label: "Cost (USD)",
    align: "right",
    render: (v) => (v != null ? `$${Number(v).toFixed(4)}` : "\u2014"),
  },
];

export default function DashboardPage() {
  const { data, loading, error } = useAdminApi("/api/admin/stats");

  const agg = data?.aggregate ?? {};
  const perUser = data?.per_user ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 mb-3">
          Overview &middot; Last 30 Days
        </h2>
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
          <StatsCard
            icon={<Users size={14} />}
            label="Total Users"
            value={agg.total_users ?? "\u2014"}
            loading={loading}
          />
          <StatsCard
            icon={<Activity size={14} />}
            label="Total Requests"
            value={agg.total_records ?? "\u2014"}
            loading={loading}
          />
          <StatsCard
            icon={<Cpu size={14} />}
            label="Total Tokens"
            value={
              agg.total_input_tokens != null
                ? (Number(agg.total_input_tokens) + Number(agg.total_output_tokens || 0)).toLocaleString()
                : "\u2014"
            }
            loading={loading}
          />
          <StatsCard
            icon={<DollarSign size={14} />}
            label="Total Cost"
            value={
              agg.total_cost_usd != null
                ? `$${Number(agg.total_cost_usd).toFixed(2)}`
                : "\u2014"
            }
            loading={loading}
          />
        </div>
      </div>

      <div>
        <h2 className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 mb-3">
          Usage by User
        </h2>
        <DataTable
          columns={USER_COLS}
          rows={perUser}
          loading={loading}
          error={error}
          emptyMessage="No usage data for this period."
        />
      </div>
    </div>
  );
}
