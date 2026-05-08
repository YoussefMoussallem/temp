import { X, UserPlus, Trash2, Crown, Edit3, Eye } from "lucide-react";
import { useEffect, useState } from "react";
import {
  addProjectMember,
  listProjectMembers,
  removeProjectMember,
  updateProjectMemberRole,
} from "../../api";

/**
 * Share-project modal.
 *
 * Renders the project's current members and (for owners) lets you invite
 * by email, change a member's role, or remove a member. A non-owner
 * member sees the same dialog read-only with one extra control: a
 * "Leave project" button on their own row.
 *
 * Identity for self-actions comes from the `currentUserOid` prop. The
 * server enforces the same checks regardless of UI state.
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

export default function ShareProjectDialog({
  open,
  onClose,
  projectId,
  projectName,
  callerRole,
  currentUserOid,
  getToken,
  onLeftProject,
}) {
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("editor");
  const [inviting, setInviting] = useState(false);

  const isOwner = callerRole === "owner";

  useEffect(() => {
    if (!open || !projectId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const token = await getToken();
        const list = await listProjectMembers(token, projectId);
        if (!cancelled) setMembers(list);
      } catch (e) {
        if (!cancelled) setError(e.message || "Failed to load members");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, projectId, getToken]);

  if (!open) return null;

  const handleInvite = async (e) => {
    e.preventDefault();
    const email = inviteEmail.trim();
    if (!email) return;
    setInviting(true);
    setError(null);
    try {
      const token = await getToken();
      const newMember = await addProjectMember(token, projectId, {
        email,
        role: inviteRole,
      });
      setMembers((prev) => [...prev, newMember]);
      setInviteEmail("");
    } catch (e) {
      setError(parseError(e, "Failed to invite"));
    } finally {
      setInviting(false);
    }
  };

  const handleRoleChange = async (userId, role) => {
    setError(null);
    try {
      const token = await getToken();
      await updateProjectMemberRole(token, projectId, userId, { role });
      setMembers((prev) => prev.map((m) => (m.user_id === userId ? { ...m, role } : m)));
    } catch (e) {
      setError(parseError(e, "Failed to update role"));
    }
  };

  const handleRemove = async (userId) => {
    setError(null);
    try {
      const token = await getToken();
      await removeProjectMember(token, projectId, userId);
      setMembers((prev) => prev.filter((m) => m.user_id !== userId));
      if (userId === currentUserOid && onLeftProject) {
        onLeftProject();
      }
    } catch (e) {
      setError(parseError(e, "Failed to remove member"));
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl w-[520px] max-h-[80vh] flex flex-col shadow-2xl shadow-black/10 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-semibold">Share project</h2>
            <p className="text-[11px] text-gray-500 mt-0.5 truncate max-w-[400px]">
              {projectName}
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-lg hover:bg-gray-100 flex items-center justify-center transition-colors cursor-pointer"
          >
            <X size={16} className="text-gray-400" />
          </button>
        </div>

        <div className="px-6 py-5 overflow-y-auto flex-1">
          {isOwner && (
            <form onSubmit={handleInvite} className="mb-5">
              <label className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 block mb-2">
                Invite by email
              </label>
              <div className="flex gap-2">
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
                  disabled={inviting || !inviteEmail.trim()}
                  className="px-3 h-9 rounded-xl bg-brand text-white text-[12px] font-semibold disabled:opacity-40 hover:bg-brand/90 transition-colors flex items-center gap-1.5"
                >
                  <UserPlus size={13} />
                  {inviting ? "Adding…" : "Add"}
                </button>
              </div>
              <p className="mt-1.5 text-[10px] text-gray-400">
                The person needs to have logged into Edwin at least once.
              </p>
            </form>
          )}

          <div>
            <div className="flex items-baseline justify-between mb-2">
              <label className="text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                Members
              </label>
              <span className="text-[10px] text-gray-400">
                {members.length} {members.length === 1 ? "person" : "people"}
              </span>
            </div>

            {loading && members.length === 0 && (
              <div className="text-[12px] text-gray-400 py-4 text-center">Loading…</div>
            )}

            <ul className="divide-y divide-gray-100">
              {members.map((m) => {
                const isSelf = m.user_id === currentUserOid;
                const memberIsOwner = m.role === "owner";
                const canChangeRole = isOwner && !memberIsOwner;
                const canRemove = !memberIsOwner && (isOwner || isSelf);
                return (
                  <li
                    key={m.user_id}
                    className="flex items-center gap-3 py-2.5"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] text-gray-900 truncate">
                        {m.display_name || m.email}
                        {isSelf && (
                          <span className="text-[11px] text-gray-400 font-normal ml-1.5">
                            (you)
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-gray-500 truncate">{m.email}</div>
                    </div>

                    {canChangeRole ? (
                      <select
                        value={m.role}
                        onChange={(e) => handleRoleChange(m.user_id, e.target.value)}
                        className="px-2 py-1 text-[11px] bg-gray-50 rounded-lg outline-none cursor-pointer border border-gray-200/60 hover:border-gray-300 focus:border-brand/30 focus:ring-2 focus:ring-brand/5"
                      >
                        <option value="editor">Editor</option>
                        <option value="viewer">Viewer</option>
                      </select>
                    ) : (
                      <RoleBadge role={m.role} />
                    )}

                    {canRemove && (
                      <button
                        type="button"
                        onClick={() => {
                          const msg = isSelf
                            ? "Leave this project?"
                            : `Remove ${m.email}?`;
                          if (confirm(msg)) handleRemove(m.user_id);
                        }}
                        className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:text-red-500 hover:bg-red-50 transition-all"
                        title={isSelf ? "Leave project" : "Remove member"}
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>

          {error && (
            <div className="mt-4 text-[12px] text-red-600 bg-red-50 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function parseError(e, fallback) {
  if (!e) return fallback;
  const msg = e.message || String(e);
  // Backend returns "HTTP 404: <body>"; surface a friendly form for known cases.
  if (msg.includes("404") && msg.toLowerCase().includes("edwin user")) {
    return "No Edwin user with that email — they need to log in once first.";
  }
  if (msg.includes("409")) return "That user is already a member.";
  if (msg.includes("400")) return "That role isn't allowed.";
  return msg.replace(/^HTTP \d+:\s*/, "") || fallback;
}
