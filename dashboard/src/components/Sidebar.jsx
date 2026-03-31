function LinkedItem({ item, className = "" }) {
  // Accepts either a string (legacy) or {title, url} object
  const title = typeof item === "string" ? item : item.title
  const url   = typeof item === "string" ? null  : item.url

  if (url) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className={`hover:underline hover:text-civic-600 transition-colors ${className}`}
      >
        {title}
      </a>
    )
  }
  return <span className={className}>{title}</span>
}

export default function Sidebar({ upcoming, recentNews, consistencyFlags }) {
  return (
    <div className="space-y-5">

      {/* Upcoming */}
      <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400 mb-3">
          On the Horizon
        </h2>
        <ul className="space-y-2">
          {upcoming?.map((item, i) => (
            <li key={i} className="flex gap-2 text-sm text-gray-700">
              <span className="text-civic-500 mt-0.5 shrink-0">›</span>
              <LinkedItem item={item} />
            </li>
          ))}
        </ul>
      </div>

      {/* Consistency flags */}
      {consistencyFlags?.length > 0 && (
        <div className="bg-amber-50 rounded-xl border border-amber-200 p-5 shadow-sm">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-amber-700 mb-3">
            Worth Watching
          </h2>
          <ul className="space-y-3">
            {consistencyFlags.map((flag, i) => (
              <li key={i} className="text-sm text-amber-900">
                <span className="font-semibold">{flag.council_member}:</span>{" "}
                {flag.observation}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Recent news */}
      <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400 mb-3">
          City News
        </h2>
        <ul className="space-y-2">
          {recentNews?.map((item, i) => (
            <li key={i} className="text-sm text-gray-600 border-b border-gray-50 pb-2 last:border-0 last:pb-0">
              <LinkedItem item={item} className="text-gray-600" />
            </li>
          ))}
        </ul>
      </div>

    </div>
  )
}
