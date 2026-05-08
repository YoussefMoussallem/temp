import { useCallback, useState } from "react";
import { AlertCircle, Check, FlaskConical, Loader2 } from "lucide-react";
import { buildAndDownloadDomPptx } from "../../agent/tools/ExportDeckTool/index.js";
import { useDeck } from "../../context/DeckContext.jsx";

const SUCCESS_RESET_MS = 2000;

export default function ExportDeckDomButton() {
  const { slides } = useDeck();
  const [phase, setPhase] = useState("idle");
  const [progressText, setProgressText] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  const slideCount = slides.length;
  const inFlight = phase === "rendering" || phase === "writing";
  const disabled = (slideCount === 0 || inFlight) && phase !== "error";

  const reset = useCallback(() => {
    setPhase("idle");
    setProgressText("");
    setErrorMsg("");
  }, []);

  const handleClick = useCallback(async () => {
    if (phase === "error") {
      reset();
      return;
    }
    if (disabled) return;

    setPhase("rendering");
    setProgressText(`Rendering 0 / ${slideCount} slides…`);
    setErrorMsg("");

    try {
      await buildAndDownloadDomPptx({
        slides,
        filename: "presentation-dom.pptx",
        onProgress: ({ phase: nextPhase, current = 0, total = slideCount }) => {
          if (nextPhase === "write") {
            setPhase("writing");
            setProgressText("Creating .pptx…");
          } else if (nextPhase === "render") {
            setPhase("rendering");
            setProgressText(`Rendering ${current} / ${total} slides…`);
          }
        },
      });

      setPhase("success");
      setProgressText("");
      window.setTimeout(() => {
        setPhase((p) => (p === "success" ? "idle" : p));
      }, SUCCESS_RESET_MS);
    } catch (err) {
      setPhase("error");
      setErrorMsg(err instanceof Error ? err.message : "DOM export failed");
    }
  }, [phase, disabled, slideCount, slides, reset]);

  let icon;
  let label;
  let stateClass;
  if (inFlight) {
    icon = <Loader2 size={13} className="animate-spin" />;
    label = progressText || "DOM exporting…";
    stateClass = "text-amber-700 bg-amber-50 cursor-wait";
  } else if (phase === "success") {
    icon = <Check size={13} />;
    label = "DOM downloaded";
    stateClass = "text-emerald-700 bg-emerald-50 cursor-default";
  } else if (phase === "error") {
    icon = <AlertCircle size={13} />;
    label = "Retry DOM";
    stateClass = "text-red-600 bg-red-50 hover:bg-red-100 cursor-pointer";
  } else {
    icon = <FlaskConical size={13} />;
    label = "DOM Export";
    stateClass = disabled
      ? "text-gray-300 cursor-not-allowed"
      : "text-amber-700 bg-amber-50 hover:bg-amber-100 cursor-pointer";
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled}
      title={
        phase === "error"
          ? `DOM export failed: ${errorMsg}. Click to retry.`
          : slideCount === 0
            ? "Add at least one slide to export"
            : "Experimental: export from rendered slide HTML without LLM conversion"
      }
      className={`h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-[11px] font-medium transition-colors ${stateClass}`}
    >
      {icon}
      <span className="truncate max-w-[200px]">{label}</span>
    </button>
  );
}
