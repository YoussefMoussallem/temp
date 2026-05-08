import { useCallback, useRef, useState } from "react";
import { Download, Loader2, AlertCircle, Check } from "lucide-react";
import { streamExportDeck } from "../../agent/client.js";
import { buildAndDownloadPptx } from "../../agent/tools/ExportDeckTool/index.js";
import { useDeck } from "../../context/DeckContext.jsx";

// Same backend pipeline as the agent's ExportDeck tool, exposed as a
// one-click button: POST /api/agent/export-deck streams progress +
// deck spec via SSE; we hand the spec to pptxgenjs in the browser to
// download a fully editable .pptx.
//
// Sized to match the panel-toggle buttons in <Header>: h-8 px-2.5
// rounded-lg / text-[11px]. Subtle brand tint so it reads as a primary
// action without shouting; the running state shows the per-slide
// progress text inline ("Converting 5 / 12 slides…").
//
// `phase` lifecycle:
//   "idle"     → "Export" (Download icon)
//   "running"  → spinner + "Converting N / M slides…"
//   "writing"  → spinner + "Assembling .pptx…"
//   "success"  → check + "Downloaded" (auto-resets after 2s)
//   "error"    → alert + "Retry" (click to reset)

const SUCCESS_RESET_MS = 2000;

export default function ExportDeckButton() {
  const { projectId, getToken, slides } = useDeck();
  const [phase, setPhase] = useState("idle");
  const [progressText, setProgressText] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const abortRef = useRef(null);

  const slideCount = slides.length;
  const inFlight = phase === "running" || phase === "writing";
  const disabled = (!projectId || slideCount === 0 || inFlight) && phase !== "error";

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

    setPhase("running");
    setProgressText(`Converting 0 / ${slideCount} slides…`);
    setErrorMsg("");

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const token = getToken ? await getToken() : null;
      let deck = null;

      for await (const evt of streamExportDeck(
        { projectId },
        { signal: controller.signal, token },
      )) {
        if (evt.event === "progress") {
          const msg = evt.data?.message || "";
          setProgressText(msg.replace("...", "…"));
          if (/Assembling/i.test(msg)) setPhase("writing");
        } else if (evt.event === "deck_export_ready") {
          deck = evt.data?.deck || null;
        } else if (evt.event === "error") {
          throw new Error(evt.data?.message || "Export failed");
        }
      }

      if (!deck) throw new Error("Export finished but no deck spec was returned.");

      setPhase("writing");
      setProgressText("Assembling .pptx…");
      await buildAndDownloadPptx(deck);

      setPhase("success");
      setProgressText("");
      window.setTimeout(() => {
        setPhase((p) => (p === "success" ? "idle" : p));
      }, SUCCESS_RESET_MS);
    } catch (err) {
      if (err?.name === "AbortError") {
        reset();
        return;
      }
      setPhase("error");
      setErrorMsg(err instanceof Error ? err.message : "Export failed");
    } finally {
      abortRef.current = null;
    }
  }, [phase, disabled, slideCount, projectId, getToken, reset]);

  let icon;
  let label;
  let stateClass;
  if (inFlight) {
    icon = <Loader2 size={13} className="animate-spin" />;
    label = progressText || "Exporting…";
    stateClass = "text-brand bg-brand-dim cursor-wait";
  } else if (phase === "success") {
    icon = <Check size={13} />;
    label = "Downloaded";
    stateClass = "text-emerald-700 bg-emerald-50 cursor-default";
  } else if (phase === "error") {
    icon = <AlertCircle size={13} />;
    label = "Retry export";
    stateClass = "text-red-600 bg-red-50 hover:bg-red-100 cursor-pointer";
  } else {
    icon = <Download size={13} />;
    label = "Export";
    stateClass = disabled
      ? "text-gray-300 cursor-not-allowed"
      : "text-brand bg-brand-dim hover:bg-brand/10 cursor-pointer";
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled}
      title={
        phase === "error"
          ? `Export failed: ${errorMsg}. Click to retry.`
          : slideCount === 0
            ? "Add at least one slide to export"
            : "Export deck to editable PowerPoint (.pptx)"
      }
      className={`h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-[11px] font-medium transition-colors ${stateClass}`}
    >
      {icon}
      <span className="truncate max-w-[200px]">{label}</span>
    </button>
  );
}
