import { useRef, useLayoutEffect, useState } from "react";

export default function SlideThumbnail({ html }) {
  const containerRef = useRef(null);
  const [scale, setScale] = useState(null);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const updateScale = () => {
      setScale(el.offsetWidth / 960);
    };
    updateScale();

    const ro = new ResizeObserver(updateScale);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div
      ref={containerRef}
      className="rounded-xl overflow-hidden bg-white ring-1 ring-gray-200/60 shadow-sm"
      style={{
        position: "relative",
        width: "100%",
        paddingTop: "56.25%", /* 16:9 */
      }}
    >
      <iframe
        srcDoc={`<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { width: 960px; height: 540px; overflow: hidden; font-family: 'Segoe UI', system-ui, sans-serif; }
</style>
</head>
<body>${html}</body>
</html>`}
        sandbox=""
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: 960,
          height: 540,
          border: "none",
          transformOrigin: "top left",
          transform: scale != null ? `scale(${scale})` : "scale(1)",
          opacity: scale != null ? 1 : 0,
          display: "block",
        }}
        title="Slide preview"
      />
    </div>
  );
}
