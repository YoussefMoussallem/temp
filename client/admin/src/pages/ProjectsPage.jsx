import { useState } from "react";
import { Settings } from "lucide-react";
import DataTable from "../components/DataTable";
import AdminProjectDialog from "../components/AdminProjectDialog";
import { useAdminApi } from "../hooks/useAdminApi";

/**
 * Admin / Projects — every project in the system.
 *
 * Columns: name, owner, member count, conversation count, lifetime
 * input/output token totals (summed from the project's conversations),
 * last updated. Clicking a row opens the management dialog.
 */
export default function ProjectsPage() {
  const { data, loading, error, refetch } = useAdminApi("/api/admin/projects");
  const projects = data?.projects ?? [];
  const [active, setActive] = useState(null);

  const COLS = [
    { key: "name", label: "Project" },
    { key: "owner_email", label: "Owner" },
    {
      key: "member_count",
      label: "Members",
      align: "right",
      render: (v) => Number(v ?? 0).toLocaleString(),
    },
    {
      key: "conversation_count",
      label: "Conversations",
      align: "right",
      render: (v) => Number(v ?? 0).toLocaleString(),
    },
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
      label: "Cost",
      align: "right",
      render: (v) => (v != null ? `$${Number(v).toFixed(4)}` : "\u2014"),
    },
    {
      key: "updated_at",
      label: "Updated",
      render: (v) => (v ? new Date(v).toLocaleDateString() : "\u2014"),
    },
    {
      key: "_manage",
      label: "",
      align: "right",
      render: (_v, row) => (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setActive(row);
          }}
          className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium text-brand bg-brand/10 hover:bg-brand/20 transition-colors"
        >
          <Settings size={11} />
          Manage
        </button>
      ),
    },
  ];

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-[10px] font-semibold uppercase tracking-widest text-gray-400">
          All Projects
        </h2>
        {projects.length > 0 && (
          <span className="text-brand bg-brand-dim px-1.5 py-0.5 rounded-full text-[10px] font-bold">
            {projects.length}
          </span>
        )}
      </div>

      <DataTable
        columns={COLS}
        rows={projects}
        loading={loading}
        error={error}
        emptyMessage="No projects yet."
      />

      <AdminProjectDialog
        project={active}
        open={!!active}
        onClose={() => setActive(null)}
        onProjectChanged={() => {
          refetch();
        }}
        onProjectDeleted={() => {
          setActive(null);
          refetch();
        }}
      />
    </div>
  );
}
