import { Sparkles } from "lucide-react";

export default function SkillsResult({ data }) {
  if (!data.skills?.length) {
    return <p className="text-[12px] text-gray-400 italic">No skills registered.</p>;
  }

  return (
    <div className="grid gap-1">
      {data.skills.map((skill) => (
        <div key={skill.name} className="flex items-start gap-2 px-2.5 py-1.5 rounded-lg hover:bg-white/60 transition-colors">
          <Sparkles size={11} className="text-brand mt-0.5 shrink-0" />
          <div className="min-w-0">
            <div className="flex items-baseline gap-1.5">
              <span className="text-[12px] font-semibold text-gray-700">{skill.name}</span>
              {skill.aliases.length > 0 && (
                <span className="text-[9px] text-gray-400">({skill.aliases.join(", ")})</span>
              )}
            </div>
            <div className="text-[11px] text-gray-400">{skill.description}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
