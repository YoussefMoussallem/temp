const SKELETON_WIDTHS = ["60%", "80%", "45%", "70%", "55%", "65%", "50%", "75%"];

export default function DataTable({ columns, rows, loading, error, emptyMessage }) {
  return (
    <div className="rounded-xl bg-white border border-gray-100 shadow-sm overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100">
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={`px-4 py-3 text-[10px] font-semibold uppercase tracking-widest text-gray-400 whitespace-nowrap ${
                    col.align === "right" ? "text-right" : "text-left"
                  }`}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading &&
              Array.from({ length: 8 }, (_, i) => (
                <tr key={i} className="border-b border-gray-50">
                  {columns.map((col, ci) => (
                    <td key={col.key} className="px-4 py-3">
                      <div
                        className="h-3.5 rounded bg-gray-100 animate-pulse"
                        style={{ width: SKELETON_WIDTHS[(i + ci) % SKELETON_WIDTHS.length] }}
                      />
                    </td>
                  ))}
                </tr>
              ))}

            {!loading && error && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-[12px] text-red-400">
                  Failed to load data.
                </td>
              </tr>
            )}

            {!loading && !error && rows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-[12px] text-gray-400">
                  {emptyMessage ?? "No data."}
                </td>
              </tr>
            )}

            {!loading &&
              !error &&
              rows.map((row, i) => (
                <tr
                  key={row.id ?? i}
                  className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50 transition-colors"
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={`px-4 py-3 text-[12px] text-gray-600 whitespace-nowrap ${
                        col.align === "right" ? "text-right" : ""
                      }`}
                    >
                      {col.render ? col.render(row[col.key], row) : (row[col.key] ?? "\u2014")}
                    </td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
