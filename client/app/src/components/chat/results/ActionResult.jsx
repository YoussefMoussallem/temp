import { Check, Download, Copy, Shrink, Bookmark, X } from "lucide-react";

const ICONS = {
  export: { download: Download, clipboard: Copy },
  compact: { true: Shrink, false: X },
  remember: Bookmark,
};

export default function ActionResult({ command, data, value }) {
  let Icon = Check;
  let color = "text-green-600 bg-green-50";

  if (command === "export") {
    Icon = data?.mode === "clipboard" ? Copy : Download;
    if (data?.error) { Icon = X; color = "text-red-500 bg-red-50"; }
  } else if (command === "compact") {
    if (!data?.success) { Icon = X; color = "text-red-500 bg-red-50"; }
    else { Icon = Shrink; }
  } else if (command === "remember") {
    Icon = Bookmark;
  }

  return (
    <div className="flex items-center gap-2.5">
      <div className={`w-6 h-6 rounded-lg flex items-center justify-center shrink-0 ${color}`}>
        <Icon size={13} />
      </div>
      <span className="text-[12px] text-gray-600">{value}</span>
    </div>
  );
}
