import { useEffect, useState } from "react";
import { X, UserPlus, Trash2, Crown, Edit3, Eye, ArrowRightLeft, Save } from "lucide-react";
import { useAdminApi, useAdminMutation } from "../hooks/useAdminApi";

/**
 * Admin / Project management modal.
 *
 * Three sections, top to bottom:
 *  1. Header: project name + owner + token totals at a glance.
 *  2. Details: editable name + description (admin rename); transfer
 *     ownership (email of new owner); delete project.
 *  3. Members: invite by email (editor / viewer), per-row role
 *     dropdown, remove button. The owner row is always read-only here
 *     — to change the owner, use Transfer ownership (which demotes the
 *     old owner to editor in one transaction).
 *
 * All mutations route through ``/api/admin/...`` and call
 * ``onProjectChanged`` (parent refetches the project list) after
 * success. ``onProjectDeleted`` closes the modal.
 */

const ROLE_META = {
  owner: { label: "Owner", icon: Crown, color: "text-amber-600 bg-amber-50" },
  editor: { label: "Editor", icon: Edit3, color: "text-blue-600 bg-blue-50" },
  viewer: { label: "Viewer", icon: Eye, color: "text-gray-600 bg-gray-100" },
};

function RoleBadge({ role }) {
  const meta = ROLE_META[role] || ROLE_META.viewer;
  const Icon = meta.icon;
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${meta.color}`}
    >
      <Icon size={10} />
      {meta.label}
    </span>
  );
}

/**
 * Per-conversation breakdown for the open project. Lazy-fetches via
 * the admin endpoint (which bypasses ``require_project_access``) and
 * renders a compact table with the same token/cost columns as the
 * project list, scoped to one project.
 */
function ConversationsSection({ projectId }) {
  const url = projectId ? `/api/admin/projects/${projectId}/conversations` : "";
  const { data, loading, error } = useAdminApi(url);
  const conversations = data?.conversations ?? [];

  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <label className="text-[10px] font-semibold uppercase tracking-widest text-gray-400">
          Conversations
        </label>
        <span className="text-[10px] text-gray-400">
          {conversations.length}{" "}
          {conversations.length === 1 ? "conversation" : "conversations"}
        </span>
      </div>

      {loading && conversations.length === 0 && (
        <div className="text-[12px] text-gray-400 py-3 text-center">Loading…</div>
      )}
      {error && !loading && (
        <div className="text-[12px] text-red-500 py-3 text-center">
          Failed to load conversations.
        </div>
      )}
      {!loading && !error && conversations.length === 0 && (
        <div className="text-[12px] text-gray-400 py-3 text-center">
          No conversations yet.
        </div>
      )}

      {conversations.length > 0 && (
        <div className="rounded-xl border border-gray-100 overflow-hidden">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/60">
                <th className="text-left px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                  Title
                </th>
                <th className="text-right px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                  Msgs
                </th>
                <th className="text-right px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                  In
                </th>
                <th className="text-right px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                  Out
                </th>
                <th className="text-right px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                  Cost
                </th>
                <th className="text-right px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                  Last active
                </th>
              </tr>
            </thead>
            <tbody>
              {conversations.map((c) => (
                <tr
                  key={c.id}
                  className="border-b border-gray-50 last:border-0 hover:bg-gray-50/40"
                >
                  <td className="px-3 py-2 text-gray-700 truncate max-w-[180px]">
                    {c.title || "Untitled"}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-500">
                    {Number(c.message_count ?? 0).toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-500">
                    {Number(c.total_input_tokens ?? 0).toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-500">
                    {Number(c.total_output_tokens ?? 0).toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right text-emerald-700 font-medium">
                    ${Number(c.total_cost_usd ?? 0).toFixed(4)}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-400">
                    {c.last_active_at
                      ? new Date(c.last_active_at).toLocaleDateString()
                      : "\u2014"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function AdminProjectDialog({
  project,
  open,
  onClose,
  onProjectChanged,
  onProjectDeleted,
}) {
  const projectId = project?.id;
  const membersUrl = projectId ? `/api/admin/projects/${projectId}/members` : null;
  const { data: membersData, loading: loadingMembers, refetch: refetchMembers } =
    useAdminApi(membersUrl ?? "");
  const members = membersData?.members ?? [];

  const { mutate, busy } = useAdminMutation();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("editor");
  const [transferEmail, setTransferEmail] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => {
    if (project) {
      setName(project.name ?? "");
      setDescription(project.description ?? "");
      setInviteEmail("");
      setTransferEmail("");
      setError(null);
    }
  }, [project]);

  if (!open || !project) return null;

  const handleErr = (e) => setError(e?.message?.replace(/^HTTP \d+:\s*/, "") || "Request failed");

  const handleSaveDetails = async () => {
    setError(null);
    try {
      await mutate("PATCH", `/api/admin/projects/${projectId}`, {
        name: name.trim() || null,
        description: description.trim() || null,
      });
      onProjectChanged?.();
    } catch (e) {
      handleErr(e);
    }
  };

  const handleDeleteProject = async () => {
    if (!confirm(`Delete "${project.name}"? This removes its conversations, messages, and slides for everyone.`)) {
      return;
    }
    setError(null);
    try {
      await mutate("DELETE", `/api/admin/projects/${projectId}`);
      onProjectDeleted?.();
    } catch (e) {
      handleErr(e);
    }
  };

  const handleTransfer = async () => {
    const email = transferEmail.trim();
    if (!email) return;
    if (!confirm(`Transfer "${project.name}" to ${email}? The current owner (${project.owner_email}) will become an editor.`)) {
      return;
    }
    setError(null);
    try {
      await mutate("POST", `/api/admin/projects/${projectId}/transfer`, {
        new_owner_email: email,
      });
      setTransferEmail("");
      onProjectChanged?.();
      refetchMembers();
    } catch (e) {
      handleErr(e);
    }
  };

  const handleAddMember = async (e) => {
    e.preventDefault();
    const email = inviteEmail.trim();
    if (!email) return;
    setError(null);
    try {
      await mutate("POST", `/api/admin/projects/${projectId}/members`, {
        email,
        role: inviteRole,
      });
      setInviteEmail("");
      refetchMembers();
      onProjectChanged?.();
    } catch (e) {
      handleErr(e);
    }
  };

  const handleRoleChange = async (userId, role) => {
    setError(null);
    try {
      await mutate(
        "PATCH",
        `/api/admin/projects/${projectId}/members/${userId}`,
        { role },
      );
      refetchMembers();
    } catch (e) {
      handleErr(e);
    }
  };

  const handleRemoveMember = async (userId, email) => {
    if (!confirm(`Remove ${email} from this project?`)) return;
    setError(null);
    try {
      await mutate(
        "DELETE",
        `/api/admin/projects/${projectId}/members/${userId}`,
      );
      refetchMembers();
      onProjectChanged?.();
    } catch (e) {
      handleErr(e);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl w-[640px] max-h-[88vh] flex flex-col shadow-2xl shadow-black/10 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold truncate">{project.name}</h2>
            <p className="text-[11px] text-gray-500 mt-0.5">
              Owner: {project.owner_email}
              {project.member_count != null && (
                <span className="ml-2 text-gray-400">
                  · {project.member_count} member{project.member_count === 1 ? "" : "s"}
                </span>
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-lg hover:bg-gray-100 flex items-center justify-center transition-colors cursor-pointer"
          >
            <X size={16} className="text-gray-400" />
          </button>
        </div>

        <div className="px-6 py-5 overflow-y-auto flex-1 space-y-6">
          {/* Lifetime totals — token counters + cost summed across the
              project's conversations. Cost rendered to 4 decimal places
              to match the user-usage dashboard. */}
          <div className="grid grid-cols-4 gap-3">
            <div className="rounded-xl bg-gray-50 px-4 py-3">
              <div className="text-[10px] uppercase tracking-widest text-gray-400 font-semibold">
                Input tokens
              </div>
              <div className="text-[15px] font-semibold text-gray-900 mt-1">
                {Number(project.total_input_tokens ?? 0).toLocaleString()}
              </div>
            </div>
            <div className="rounded-xl bg-gray-50 px-4 py-3">
              <div className="text-[10px] uppercase tracking-widest text-gray-400 font-semibold">
                Output tokens
              </div>
              <div className="text-[15px] font-semibold text-gray-900 mt-1">
                {Number(project.total_output_tokens ?? 0).toLocaleString()}
              </div>
            </div>
            <div className="rounded-xl bg-emerald-50/50 px-4 py-3">
              <div className="text-[10px] uppercase tracking-widest text-emerald-700/70 font-semibold">
                Cost (USD)
              </div>
              <div className="text-[15px] font-semibold text-emerald-700 mt-1">
                ${Number(project.total_cost_usd ?? 0).toFixed(4)}
              </div>
            </div>
            <div className="rounded-xl bg-gray-50 px-4 py-3">
              <div className="text-[10px] uppercase tracking-widest text-gray-400 font-semibold">
                Conversations
              </div>
              <div className="text-[15px] font-semibold text-gray-900 mt-1">
                {Number(project.conversation_count ?? 0).toLocaleString()}
              </div>
            </div>
          </div>

          <ConversationsSection projectId={projectId} />


          {/* Details */}
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 block mb-2">
              Project details
            </label>
            <div className="flex flex-col gap-2">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Project name"
                className="px-3 py-2 text-sm bg-gray-50 rounded-xl outline-none border border-gray-200/60 hover:border-gray-300 focus:border-brand/30 focus:ring-2 focus:ring-brand/5"
              />
              <input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Description"
                className="px-3 py-2 text-sm bg-gray-50 rounded-xl outline-none border border-gray-200/60 hover:border-gray-300 focus:border-brand/30 focus:ring-2 focus:ring-brand/5"
              />
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={handleSaveDetails}
                  disabled={busy}
                  className="inline-flex items-center gap-1.5 px-3 h-9 rounded-xl bg-brand text-white text-[12px] font-semibold disabled:opacity-40 hover:bg-brand/90 transition-colors"
                >
                  <Save size={13} />
                  Save changes
                </button>
              </div>
            </div>
          </div>

          {/* Transfer ownership */}
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 block mb-2">
              Transfer ownership
            </label>
            <div className="flex gap-2">
              <input
                type="email"
                value={transferEmail}
                onChange={(e) => setTransferEmail(e.target.value)}
                placeholder="new-owner@pwc.com"
                className="flex-1 px-3 py-2 text-sm bg-gray-50 rounded-xl outline-none border border-gray-200/60 hover:border-gray-300 focus:border-brand/30 focus:ring-2 focus:ring-brand/5"
              />
              <button
                type="button"
                onClick={handleTransfer}
                disabled={busy || !transferEmail.trim()}
                className="inline-flex items-center gap-1.5 px-3 h-9 rounded-xl bg-amber-500 text-white text-[12px] font-semibold disabled:opacity-40 hover:bg-amber-600 transition-colors"
              >
                <ArrowRightLeft size={13} />
                Transfer
              </button>
            </div>
            <p className="mt-1.5 text-[10px] text-gray-400">
              The current owner is demoted to editor and keeps access. Atomic — done in one transaction.
            </p>
          </div>

          {/* Members */}
          <div>
            <div className="flex items-baseline justify-between mb-2">
              <label className="text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                Members
              </label>
              <span className="text-[10px] text-gray-400">
                {members.length} {members.length === 1 ? "person" : "people"}
              </span>
            </div>

            <form onSubmit={handleAddMember} className="flex gap-2 mb-3">
              <input
                type="email"
                required
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="colleague@pwc.com"
                className="flex-1 px-3 py-2 text-sm bg-gray-50 rounded-xl outline-none border border-gray-200/60 hover:border-gray-300 focus:border-brand/30 focus:ring-2 focus:ring-brand/5"
              />
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value)}
                className="px-3 py-2 text-sm bg-gray-50 rounded-xl outline-none cursor-pointer border border-gray-200/60 hover:border-gray-300 focus:border-brand/30 focus:ring-2 focus:ring-brand/5"
              >
                <option value="editor">Editor</option>
                <option value="viewer">Viewer</option>
              </select>
              <button
                type="submit"
                disabled={busy || !inviteEmail.trim()}
                className="inline-flex items-center gap-1.5 px-3 h-9 rounded-xl bg-brand text-white text-[12px] font-semibold disabled:opacity-40 hover:bg-brand/90 transition-colors"
              >
                <UserPlus size={13} />
                Add
              </button>
            </form>

            {loadingMembers && members.length === 0 && (
              <div className="text-[12px] text-gray-400 py-3 text-center">Loading…</div>
            )}

            <ul className="divide-y divide-gray-100">
              {members.map((m) => {
                const isOwner = m.role === "owner";
                return (
                  <li key={m.user_id} className="flex items-center gap-3 py-2.5">
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] text-gray-900 truncate">
                        {m.display_name || m.email}
                      </div>
                      <div className="text-[11px] text-gray-500 truncate">{m.email}</div>
                    </div>
                    {isOwner ? (
                      <RoleBadge role={m.role} />
                    ) : (
                      <select
                        value={m.role}
                        onChange={(e) => handleRoleChange(m.user_id, e.target.value)}
                        disabled={busy}
                        className="px-2 py-1 text-[11px] bg-gray-50 rounded-lg outline-none cursor-pointer border border-gray-200/60 hover:border-gray-300 focus:border-brand/30 focus:ring-2 focus:ring-brand/5"
                      >
                        <option value="editor">Editor</option>
                        <option value="viewer">Viewer</option>
                      </select>
                    )}
                    {!isOwner && (
                      <button
                        type="button"
                        onClick={() => handleRemoveMember(m.user_id, m.email)}
                        disabled={busy}
                        className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:text-red-500 hover:bg-red-50 transition-all disabled:opacity-40"
                        title="Remove member"
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>

          {/* Danger zone */}
          <div className="rounded-xl border border-red-100 bg-red-50/40 px-4 py-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[12px] font-semibold text-red-700">
                  Delete project
                </div>
                <div className="text-[11px] text-red-600/80 mt-0.5">
                  Permanently removes the project and all its conversations, messages, and slides.
                </div>
              </div>
              <button
                type="button"
                onClick={handleDeleteProject}
                disabled={busy}
                className="inline-flex items-center gap-1.5 px-3 h-9 rounded-xl bg-red-500 text-white text-[12px] font-semibold disabled:opacity-40 hover:bg-red-600 transition-colors"
              >
                <Trash2 size={13} />
                Delete
              </button>
            </div>
          </div>

          {error && (
            <div className="text-[12px] text-red-600 bg-red-50 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
