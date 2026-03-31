export default function MeetingSummary({ summary, date, topics }) {
  const formatted = new Date(date + "T12:00:00").toLocaleDateString("en-US", {
    weekday: "long", year: "numeric", month: "long", day: "numeric",
  })

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-civic-500 mb-1">
            Latest Meeting
          </p>
          <h2 className="text-xl font-bold text-gray-900">{formatted}</h2>
        </div>
        <span className="shrink-0 bg-green-100 text-green-800 text-xs font-semibold px-3 py-1 rounded-full">
          Meeting Complete
        </span>
      </div>

      {topics?.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-4">
          {topics.map((t) => (
            <span key={t} className="bg-civic-50 text-civic-700 text-xs font-medium px-2.5 py-1 rounded-full border border-civic-100">
              {t}
            </span>
          ))}
        </div>
      )}

      <div className="text-gray-700 text-sm leading-relaxed space-y-3">
        {summary.split("\n\n").map((para, i) => (
          <p key={i}>{para}</p>
        ))}
      </div>
    </div>
  )
}
