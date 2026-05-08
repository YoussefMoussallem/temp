import { Monitor } from "lucide-react";
import SlideThumbnail from "./SlideThumbnail";

export default function DeckPreview({ slide }) {
  if (!slide?.html) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-gradient-to-b from-gray-50 to-gray-100">
        <div className="w-16 h-16 rounded-3xl bg-white shadow-sm flex items-center justify-center mb-5">
          <Monitor size={28} className="text-gray-300" />
        </div>
        <h2 className="text-lg font-semibold text-gray-800 mb-1.5 font-[var(--font-heading)]">
          No slide to preview
        </h2>
        <p className="text-sm text-gray-400 max-w-[260px] text-center leading-relaxed">
          Select a slide from the sidebar to see the preview.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 flex items-center justify-center bg-gradient-to-b from-gray-50 to-gray-100 p-8">
      <div className="w-full max-w-[960px] rounded-2xl overflow-hidden shadow-xl shadow-black/5">
        <SlideThumbnail html={slide.html} />
      </div>
    </div>
  );
}
