export default function UsageBlock({ usage }) {
  if (!usage) return null;
  return (
    <div className="text-[10px] text-gray-300 mt-3 font-medium">
      {usage.input_tokens?.toLocaleString()} in &middot; {usage.output_tokens?.toLocaleString()} out
    </div>
  );
}
