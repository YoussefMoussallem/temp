import { useCallback, useRef } from "react";

export default function ResizeHandle({ onResize, direction = "horizontal" }) {
  const lastPos = useRef(0);
  const activePointerId = useRef(null);

  const endDrag = useCallback((el, pointerId) => {
    if (el && pointerId != null && el.hasPointerCapture?.(pointerId)) {
      el.releasePointerCapture(pointerId);
    }
    activePointerId.current = null;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  }, []);

  const onPointerDown = useCallback(
    (e) => {
      if (e.button !== undefined && e.button !== 0) return;
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      activePointerId.current = e.pointerId;
      lastPos.current = direction === "horizontal" ? e.clientX : e.clientY;
      document.body.style.cursor = direction === "horizontal" ? "col-resize" : "row-resize";
      document.body.style.userSelect = "none";
    },
    [direction],
  );

  const onPointerMove = useCallback(
    (e) => {
      if (activePointerId.current !== e.pointerId) return;
      const pos = direction === "horizontal" ? e.clientX : e.clientY;
      const delta = pos - lastPos.current;
      lastPos.current = pos;
      if (delta !== 0) onResize(delta);
    },
    [onResize, direction],
  );

  const onPointerEnd = useCallback(
    (e) => {
      if (activePointerId.current !== e.pointerId) return;
      endDrag(e.currentTarget, e.pointerId);
    },
    [endDrag],
  );

  return (
    <div
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerEnd}
      onPointerCancel={onPointerEnd}
      onLostPointerCapture={onPointerEnd}
      style={{ touchAction: "none" }}
      className={`shrink-0 flex items-center justify-center group
        ${direction === "horizontal"
          ? "w-1.5 cursor-col-resize hover:bg-brand/10 active:bg-brand/20"
          : "h-1.5 cursor-row-resize hover:bg-brand/10 active:bg-brand/20"
        } transition-colors`}
    >
      <div
        className={`rounded-full bg-gray-300 group-hover:bg-brand/40 group-active:bg-brand transition-colors
          ${direction === "horizontal" ? "w-0.5 h-8" : "h-0.5 w-8"}`}
      />
    </div>
  );
}
