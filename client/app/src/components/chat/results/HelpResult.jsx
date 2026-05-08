import { Slash } from "lucide-react";

export default function HelpResult({ data }) {
  return (
    <div className="grid gap-1">
      {data.commands.map((cmd) => (
        <div key={cmd.name} className="flex items-baseline gap-2 px-2.5 py-1.5 rounded-lg hover:bg-white/60 transition-colors">
          <div className="flex items-center gap-1 shrink-0">
            <Slash size={10} className="text-brand" />
            <span className="text-[12px] font-semibold font-mono text-gray-700">{cmd.name}</span>
          </div>
          <span className="text-[11px] text-gray-400 truncate">{cmd.description}</span>
        </div>
      ))}
    </div>
  );
}
