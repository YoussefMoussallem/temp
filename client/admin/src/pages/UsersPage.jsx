import { useState } from "react";
import { Trash2 } from "lucide-react";
import DataTable from "../components/DataTable";
import { useAdminApi, useAdminMutation } from "../hooks/useAdminApi";

export default function UsersPage() {
  const { data, loading, error, refetch } = useAdminApi("/api/admin/users");
  const users = data?.users ?? [];
  const { mutate, busy } = useAdminMutation();
  const [deleteError, setDeleteError] = useState(null);

  const handleDelete = async (user) => {
    const msg =
      `Permanently delete ${user.email}?\n\n` +
      "This will also delete every project they own and all of " +
      "those projects' conversations, messages, and slides. " +
      "Their participation in OTHER people's projects is removed " +
      "but those projects keep going.\n\n" +
      "This cannot be undone.";
    if (!confirm(msg)) return;
    setDeleteError(null);
    try {
      await mutate("DELETE", `/api/admin/users/${user.azure_oid}`);
      refetch();
    } catch (e) {
      setDeleteError(e?.message?.replace(/^HTTP \d+:\s*/, "") || "Failed to delete user");
    }
  };

  const COLS = [
    { key: "email", label: "Email" },
    { key: "display_name", label: "Name" },
    {
      key: "created_at",
      label: "Joined",
      render: (v) => (v ? new Date(v).toLocaleDateString() : "\u2014"),
    },
    {
      key: "azure_oid",
      label: "Azure OID",
      render: (v) =>
        v ? <span className="font-mono text-[10px] text-gray-400">{v}</span> : "\u2014",
    },
    {
      key: "_delete",
      label: "",
      align: "right",
      render: (_v, row) => (
        <button
          type="button"
          disabled={busy}
          onClick={(e) => {
            e.stopPropagation();
            handleDelete(row);
          }}
          className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium text-red-500 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-40"
          title="Delete user (cascades to all owned projects)"
        >
          <Trash2 size={11} />
          Delete
        </button>
      ),
    },
  ];

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-[10px] font-semibold uppercase tracking-widest text-gray-400">
          All Users
        </h2>
        {users.length > 0 && (
          <span className="text-brand bg-brand-dim px-1.5 py-0.5 rounded-full text-[10px] font-bold">
            {users.length}
          </span>
        )}
      </div>

      {deleteError && (
        <div className="mb-3 text-[12px] text-red-600 bg-red-50 rounded-lg px-3 py-2">
          {deleteError}
        </div>
      )}

      <DataTable
        columns={COLS}
        rows={users}
        loading={loading}
        error={error}
        emptyMessage="No users found."
      />
    </div>
  );
}
