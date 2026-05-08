import { useState, useEffect, useRef } from "react";
import { Monitor, Presentation, X } from "lucide-react";
import SlideThumbnail from "./SlideThumbnail";
import Skeleton from "../common/Skeleton";

// Native HTML5 drag-and-drop. The filmstrip is a small vertical list of
// thumbnails — no need for a dedicated dnd library.
//
// `dropIndex` is the *insertion index* in the current `slides` array (i.e.
// the position the dragged slide would land at if dropped now), 0..n. The
// thin coloured bar between thumbnails is the drop indicator.
//
// On drop we forward `(fromIndex, toIndexAfterRemoval)` to the parent —
// the deck context resolves the target after_slide_id and calls the API.
//
// Delete UX: a small "X" appears in the top-right corner on hover. Clicking
// it doesn't delete immediately — it swaps the card content for an inline
// "Delete this slide?" confirmation. ESC dismisses; the confirmation
// autofocuses Cancel so a stray Enter doesn't destroy a slide.
//
// Keyboard nav: clicking anywhere in the scroll area focuses it. While
// focused, ArrowUp / ArrowLeft moves to the previous slide and ArrowDown /
// ArrowRight to the next. The selected thumbnail auto-scrolls into view.
export default function SlideFilmstrip({
  slides,
  selectedIndex,
  onSelect,
  onReorder,
  onDelete,
  isLoading = false,
  readOnly = false,
}) {
  const [dragIndex, setDragIndex] = useState(null);
  const [dropIndex, setDropIndex] = useState(null);
  const [pendingDeleteId, setPendingDeleteId] = useState(null);
  const listRef = useRef(null);

  const draggable = !readOnly && typeof onReorder === "function";
  const canDelete = !readOnly && typeof onDelete === "function";

  // ESC dismisses the delete confirmation. Scoped to when one is open so
  // we don't keep a global listener active otherwise.
  useEffect(() => {
    if (pendingDeleteId === null) return;
    const handler = (e) => {
      if (e.key === "Escape") setPendingDeleteId(null);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [pendingDeleteId]);

  // If the slide vanishes from the list (e.g. SSE-driven delete from the
  // agent landed first), drop the pending-confirm state so we don't try
  // to render a confirmation against a missing slide.
  useEffect(() => {
    if (pendingDeleteId === null) return;
    if (!slides.some((s) => s.id === pendingDeleteId)) {
      setPendingDeleteId(null);
    }
  }, [slides, pendingDeleteId]);

  // Keep the selected thumbnail visible. `block: "nearest"` only scrolls
  // when the element is actually clipped, so it's a no-op when the user
  // already has it on screen — important when slides arrive via SSE and
  // we don't want to yank the user's view around.
  useEffect(() => {
    if (selectedIndex < 0 || !listRef.current) return;
    const el = listRef.current.querySelector(
      `[data-slide-index="${selectedIndex}"]`,
    );
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedIndex]);

  const resetDrag = () => {
    setDragIndex(null);
    setDropIndex(null);
  };

  const handleDragStart = (e, index) => {
    if (!draggable) return;
    setDragIndex(index);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(index));
  };

  const handleDragOver = (e, index) => {
    if (dragIndex === null) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const rect = e.currentTarget.getBoundingClientRect();
    const isTopHalf = e.clientY < rect.top + rect.height / 2;
    setDropIndex(isTopHalf ? index : index + 1);
  };

  const handleListDragOver = (e) => {
    if (dragIndex === null) return;
    e.preventDefault();
  };

  const handleEndZoneDragOver = (e) => {
    if (dragIndex === null) return;
    e.preventDefault();
    setDropIndex(slides.length);
  };

  const handleDrop = (e) => {
    if (dragIndex === null || dropIndex === null) {
      resetDrag();
      return;
    }
    e.preventDefault();
    let to = dropIndex;
    if (dragIndex < to) to -= 1;
    if (to !== dragIndex) {
      onReorder(dragIndex, to);
    }
    resetDrag();
  };

  // Click anywhere in the scroll area to give it keyboard focus, so the
  // arrow-key handler below picks up Up/Down/Left/Right. Buttons inside
  // still take focus normally; keydown bubbles up either way.
  const handleListMouseDown = () => {
    listRef.current?.focus({ preventScroll: true });
  };

  const handleKeyDown = (e) => {
    if (pendingDeleteId !== null) return;
    if (slides.length === 0) return;
    let next = null;
    if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
      next = Math.max(0, (selectedIndex < 0 ? 0 : selectedIndex) - 1);
    } else if (e.key === "ArrowDown" || e.key === "ArrowRight") {
      next = Math.min(slides.length - 1, (selectedIndex < 0 ? -1 : selectedIndex) + 1);
    } else if (e.key === "Home") {
      next = 0;
    } else if (e.key === "End") {
      next = slides.length - 1;
    } else {
      return;
    }
    if (next !== selectedIndex) onSelect(next);
    e.preventDefault();
  };

  const confirmDelete = (slideId) => {
    setPendingDeleteId(null);
    onDelete?.(slideId);
  };

  return (
    <div className="w-full h-full bg-white/60 backdrop-blur-sm flex flex-col">
      <div className="px-4 py-3.5">
        <div className="flex items-center gap-2">
          <Presentation size={13} className="text-gray-400" />
          <span className="text-[11px] font-semibold uppercase tracking-widest text-gray-400">
            Slides
          </span>
          {slides.length > 0 && (
            <span className="ml-auto text-[10px] font-bold text-brand bg-brand-dim px-1.5 py-0.5 rounded-full">
              {slides.length}
            </span>
          )}
        </div>
      </div>

      <div
        ref={listRef}
        tabIndex={0}
        className="flex-1 overflow-y-auto px-2.5 pb-3 flex flex-col outline-none"
        onMouseDown={handleListMouseDown}
        onKeyDown={handleKeyDown}
        onDragOver={handleListDragOver}
        onDrop={handleDrop}
        onDragEnd={resetDrag}
      >
        {slides.length === 0 && isLoading ? (
          <FilmstripSkeleton />
        ) : slides.length === 0 ? (
          <div className="flex flex-col items-center justify-center text-center mt-12 px-3">
            <div className="w-12 h-12 rounded-2xl bg-gray-100 flex items-center justify-center mb-3">
              <Monitor size={22} className="text-gray-300" />
            </div>
            <p className="text-[11px] text-gray-400 leading-relaxed">
              Describe your presentation to generate slides
            </p>
          </div>
        ) : (
          <>
            {slides.map((slide, i) => {
              const isPendingDelete = pendingDeleteId === slide.id;
              const isSelected = i === selectedIndex;
              return (
                <div
                  key={slide.id}
                  data-slide-index={i}
                  className="flex flex-col"
                >
                  <DropIndicator visible={dropIndex === i} />
                  <div
                    className={`group/slide relative shrink-0 w-full rounded-xl overflow-hidden transition-all duration-200
                      ${dragIndex === i ? "opacity-40" : ""}
                      ${isSelected
                        ? "ring-2 ring-brand shadow-md shadow-brand-glow scale-[1.02]"
                        : "ring-1 ring-gray-200/80 hover:ring-gray-300 hover:shadow-sm"
                      }`}
                  >
                    <button
                      type="button"
                      draggable={draggable && !isPendingDelete}
                      onDragStart={(e) => handleDragStart(e, i)}
                      onDragOver={(e) => handleDragOver(e, i)}
                      onDragEnd={resetDrag}
                      onClick={() => onSelect(i)}
                      disabled={isPendingDelete}
                      tabIndex={-1}
                      className={`block w-full text-left
                        ${draggable && !isPendingDelete ? "cursor-grab active:cursor-grabbing" : "cursor-pointer"}
                        ${isPendingDelete ? "pointer-events-none" : ""}`}
                    >
                      <div className="pointer-events-none">
                        <SlideThumbnail html={slide.html} />
                      </div>
                      <div className={`text-[9px] py-1 text-center font-semibold transition-colors
                        ${isSelected ? "text-brand bg-brand-dim" : "text-gray-400 bg-gray-50"}`}>
                        {slide.title || i + 1}
                      </div>
                    </button>

                    {/* Hover-revealed close trigger. Tiny X with a subtle
                        white pill behind it so it stays legible on any
                        slide background. */}
                    {canDelete && !isPendingDelete && (
                      <button
                        type="button"
                        draggable={false}
                        tabIndex={-1}
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation();
                          setPendingDeleteId(slide.id);
                        }}
                        title="Delete slide"
                        aria-label="Delete slide"
                        className="absolute top-1 right-1 z-10 flex items-center justify-center
                          w-[18px] h-[18px] rounded-full bg-white/85 backdrop-blur-sm
                          ring-1 ring-gray-200/80 text-gray-500
                          opacity-0 scale-75
                          group-hover/slide:opacity-100 group-hover/slide:scale-100
                          hover:text-red-600 hover:ring-red-200 hover:bg-white
                          focus:outline-none focus:opacity-100 focus:scale-100
                          focus:ring-2 focus:ring-red-300
                          transition-all duration-150"
                      >
                        <X size={11} strokeWidth={2.5} />
                      </button>
                    )}

                    {isPendingDelete && (
                      <DeleteConfirmOverlay
                        onCancel={() => setPendingDeleteId(null)}
                        onConfirm={() => confirmDelete(slide.id)}
                      />
                    )}
                  </div>
                </div>
              );
            })}
            <DropIndicator visible={dropIndex === slides.length} />
            {/* Tail drop zone — gives the user a target below the last
                thumbnail to insert at the end. */}
            <div
              className="flex-1 min-h-6"
              onDragOver={handleEndZoneDragOver}
            />
          </>
        )}
      </div>
    </div>
  );
}

// Three skeleton "thumbnails" matching the real filmstrip cell footprint
// (16:9 aspect block + footer label bar). Three is enough to suggest
// "list of slides" without dominating the panel — most decks have more
// but the skeleton's job is just to fill first paint, not predict count.
function FilmstripSkeleton() {
  return (
    <div className="flex flex-col" aria-label="Loading slides">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="flex flex-col">
          <div className="h-0.5 my-1" />
          <div className="rounded-xl ring-1 ring-gray-200/80 overflow-hidden">
            <Skeleton className="w-full aspect-[16/9] rounded-none" />
            <Skeleton className="h-4 w-full rounded-none" />
          </div>
        </div>
      ))}
    </div>
  );
}

function DropIndicator({ visible }) {
  return (
    <div
      aria-hidden="true"
      className={`h-0.5 my-1 rounded-full transition-colors ${
        visible ? "bg-brand" : "bg-transparent"
      }`}
    />
  );
}

function DeleteConfirmOverlay({ onCancel, onConfirm }) {
  return (
    <div
      role="dialog"
      aria-label="Confirm delete slide"
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
      className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 px-2
        bg-red-500/90 backdrop-blur-[2px]"
    >
      <span className="text-[11px] font-semibold tracking-wide text-white">
        Delete this slide?
      </span>
      <div className="flex gap-1.5">
        <button
          type="button"
          autoFocus
          onClick={onCancel}
          className="text-[10px] font-medium px-2.5 py-1 rounded-md
            bg-white/15 text-white hover:bg-white/25 transition-colors
            focus:outline-none focus:ring-2 focus:ring-white/60"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          className="text-[10px] font-semibold px-2.5 py-1 rounded-md
            bg-white text-red-600 hover:bg-red-50 transition-colors
            focus:outline-none focus:ring-2 focus:ring-white"
        >
          Delete
        </button>
      </div>
    </div>
  );
}
