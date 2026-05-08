import { useState } from "react";
import { ClipboardList, Check, RotateCcw } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { proseClasses } from "../../../utils/proseClasses";

export default function ExitPlanModeUI({ request, onApprove, onReject }) {
  const plan = request?.tool_input?.plan || "";
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [submitted, setSubmitted] = useState(false);

  if (!request || !plan) return null;

  const handleApprove = () => {
    setSubmitted(true);
    onApprove?.();
  };

  const handleReject = () => {
    if (!reason.trim()) return;
    setSubmitted(true);
    onReject?.(reason.trim());
  };

  if (submitted) {
    return (
      <div className="py-2 px-1">
        <div className="rounded-xl border border-gray-100 bg-gray-50/50 px-4 py-3">
          <div className="flex items-center gap-1.5 text-[11px] text-gray-400 mb-1">
            <Check size={12} className="text-green-500" />
            <span>{reason ? "Feedback sent" : "Plan approved"}</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="py-2 px-1">
      <div className="rounded-xl border border-amber-200/60 bg-amber-50/30 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-amber-200/40 bg-amber-50/50">
          <ClipboardList size={13} className="text-amber-600" />
          <span className="text-[12px] font-semibold text-gray-700">Plan ready for review</span>
        </div>

        <div className="px-4 py-3 max-h-80 overflow-y-auto">
          <div className={proseClasses}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{plan}</ReactMarkdown>
          </div>
        </div>

        {rejecting && (
          <div className="px-4 pb-2">
            <textarea
              autoFocus
              rows={2}
              placeholder="What should be changed?"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && reason.trim() && handleReject()}
              className="w-full text-[12px] border border-gray-200 rounded-lg px-3 py-1.5 resize-none focus:outline-none focus:ring-1 focus:ring-amber-400/50 focus:border-amber-400"
            />
          </div>
        )}

        <div className="px-4 py-2.5 border-t border-amber-200/40 flex justify-end gap-2">
          {rejecting ? (
            <button
              onClick={handleReject}
              disabled={!reason.trim()}
              className={`px-4 py-1.5 rounded-lg text-[12px] font-medium transition-all cursor-pointer ${
                reason.trim()
                  ? "bg-gray-600 text-white hover:bg-gray-700"
                  : "bg-gray-100 text-gray-400 cursor-not-allowed"
              }`}
            >
              Send Feedback
            </button>
          ) : (
            <button
              onClick={() => setRejecting(true)}
              className="px-4 py-1.5 rounded-lg text-[12px] font-medium text-gray-600 border border-gray-200 hover:bg-gray-50 transition-all cursor-pointer"
            >
              <span className="flex items-center gap-1">
                <RotateCcw size={11} />
                Revise
              </span>
            </button>
          )}
          <button
            onClick={handleApprove}
            className="px-4 py-1.5 rounded-lg text-[12px] font-medium bg-brand text-white hover:bg-brand/90 transition-all cursor-pointer"
          >
            Approve Plan
          </button>
        </div>
      </div>
    </div>
  );
}
