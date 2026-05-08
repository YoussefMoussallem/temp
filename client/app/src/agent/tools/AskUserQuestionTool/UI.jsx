import { useState } from "react";
import { Check, MessageSquare } from "lucide-react";

export default function AskUserQuestionUI({ request, onSubmit }) {
  const questions = request?.tool_input?.questions || [];
  const [answers, setAnswers] = useState({});
  const [otherText, setOtherText] = useState({});
  const [submitted, setSubmitted] = useState(false);

  if (!request || questions.length === 0) return null;

  const setAnswer = (qText, value, multi) => {
    setAnswers((prev) => {
      if (!multi) return { ...prev, [qText]: value };
      const current = prev[qText] ? prev[qText].split(", ") : [];
      const next = current.includes(value)
        ? current.filter((v) => v !== value)
        : [...current, value];
      return { ...prev, [qText]: next.join(", ") };
    });
  };

  const isSelected = (qText, label, multi) => {
    if (!answers[qText]) return false;
    if (!multi) return answers[qText] === label;
    return answers[qText].split(", ").includes(label);
  };

  const allAnswered = questions.every((q) => {
    const a = answers[q.question];
    if (!a) return false;
    if (a === "__other__") return !!otherText[q.question]?.trim();
    return true;
  });

  const handleSubmit = () => {
    const finalAnswers = {};
    const annotations = {};
    for (const q of questions) {
      const raw = answers[q.question] || "";
      finalAnswers[q.question] = raw === "__other__"
        ? otherText[q.question]?.trim() || ""
        : raw;
      const opt = q.options.find((o) => o.label === raw);
      if (opt?.preview) annotations[q.question] = { preview: opt.preview };
    }
    setSubmitted(true);
    onSubmit(finalAnswers, annotations);
  };

  if (submitted) {
    return (
      <div className="py-2 px-1">
        <div className="rounded-xl border border-gray-100 bg-gray-50/50 px-4 py-3">
          <div className="flex items-center gap-1.5 text-[11px] text-gray-400 mb-1">
            <Check size={12} className="text-green-500" />
            <span>Answered</span>
          </div>
          {questions.map((q, i) => (
            <div key={i} className="text-[12px] text-gray-600">
              <span className="font-medium">{q.header}:</span>{" "}
              {answers[q.question] === "__other__"
                ? otherText[q.question]
                : answers[q.question]}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="py-2 px-1">
      <div className="rounded-xl border border-brand/15 bg-brand/[0.02] overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-brand/10 bg-brand/[0.03]">
          <MessageSquare size={13} className="text-brand" />
          <span className="text-[12px] font-semibold text-gray-700">Edwin needs your input</span>
        </div>

        <div className="px-4 py-3 space-y-5">
          {questions.map((q, qi) => (
            <div key={qi}>
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-[10px] font-medium uppercase tracking-wider text-brand bg-brand/8 px-2 py-0.5 rounded-full">
                  {q.header}
                </span>
              </div>
              <p className="text-[13px] text-gray-800 font-medium mb-2.5">{q.question}</p>

              <div className="space-y-1.5">
                {q.options.map((opt, oi) => {
                  const selected = isSelected(q.question, opt.label, q.multiSelect);
                  return (
                    <button
                      key={oi}
                      onClick={() => setAnswer(q.question, opt.label, q.multiSelect)}
                      className={`w-full text-left px-3 py-2 rounded-lg border transition-all cursor-pointer ${
                        selected
                          ? "border-brand bg-brand/5 ring-1 ring-brand/20"
                          : "border-gray-200 hover:border-gray-300 hover:bg-gray-50"
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <div className={`w-3.5 h-3.5 mt-0.5 rounded-${q.multiSelect ? "sm" : "full"} border flex-shrink-0 flex items-center justify-center ${
                          selected ? "bg-brand border-brand" : "border-gray-300"
                        }`}>
                          {selected && <Check size={9} className="text-white" />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-[12px] font-medium text-gray-800">{opt.label}</div>
                          {opt.description && (
                            <div className="text-[11px] text-gray-500 mt-0.5 leading-snug">{opt.description}</div>
                          )}
                        </div>
                      </div>
                      {opt.preview && selected && (
                        <pre className="mt-1.5 ml-5.5 text-[10px] bg-gray-800 text-gray-100 rounded-md p-2.5 overflow-x-auto whitespace-pre-wrap leading-relaxed">
                          {opt.preview}
                        </pre>
                      )}
                    </button>
                  );
                })}

                <button
                  onClick={() => setAnswer(q.question, "__other__", false)}
                  className={`w-full text-left px-3 py-2 rounded-lg border transition-all cursor-pointer ${
                    answers[q.question] === "__other__"
                      ? "border-brand bg-brand/5 ring-1 ring-brand/20"
                      : "border-gray-200 hover:border-gray-300 hover:bg-gray-50"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <div className={`w-3.5 h-3.5 rounded-full border flex-shrink-0 flex items-center justify-center ${
                      answers[q.question] === "__other__" ? "bg-brand border-brand" : "border-gray-300"
                    }`}>
                      {answers[q.question] === "__other__" && <Check size={9} className="text-white" />}
                    </div>
                    <span className="text-[12px] text-gray-500">Other</span>
                  </div>
                </button>
                {answers[q.question] === "__other__" && (
                  <input
                    type="text"
                    autoFocus
                    placeholder="Type your answer..."
                    value={otherText[q.question] || ""}
                    onChange={(e) => setOtherText((p) => ({ ...p, [q.question]: e.target.value }))}
                    onKeyDown={(e) => e.key === "Enter" && allAnswered && handleSubmit()}
                    className="w-full text-[12px] border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand/30 focus:border-brand"
                  />
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="px-4 py-2.5 border-t border-brand/10 flex justify-end">
          <button
            onClick={handleSubmit}
            disabled={!allAnswered}
            className={`px-4 py-1.5 rounded-lg text-[12px] font-medium transition-all cursor-pointer ${
              allAnswered
                ? "bg-brand text-white hover:bg-brand/90"
                : "bg-gray-100 text-gray-400 cursor-not-allowed"
            }`}
          >
            Submit
          </button>
        </div>
      </div>
    </div>
  );
}
