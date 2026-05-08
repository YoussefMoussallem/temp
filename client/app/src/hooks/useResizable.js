import { useState, useCallback, useRef } from "react";

/**
 * Manages a resizable panel width, clamped between min and max.
 * Returns current width, a ref (for drag handlers), and the resize callback.
 *
 * @param {number} initial - Starting width in px
 * @param {number} min - Minimum allowed width
 * @param {number} max - Maximum allowed width
 * @param {boolean} invert - If true, dragging right shrinks (for right-side panels)
 */
export function useResizable(initial, min, max, invert = false) {
  const [width, setWidth] = useState(initial);
  const widthRef = useRef(initial);

  const onResize = useCallback(
    (delta) => {
      const d = invert ? -delta : delta;
      const next = Math.max(min, Math.min(max, widthRef.current + d));
      widthRef.current = next;
      setWidth(next);
    },
    [min, max, invert],
  );

  return { width, onResize };
}
