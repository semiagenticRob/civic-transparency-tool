export default function AlertBanner({ alerts }) {
  if (!alerts?.length) return null

  return (
    <div className="space-y-2 mb-6">
      {alerts.map((alert, i) => (
        <div
          key={i}
          className={`flex items-start gap-3 px-4 py-3 rounded-lg text-sm font-medium ${
            alert.severity === "warning"
              ? "bg-amber-50 border border-amber-200 text-amber-900"
              : "bg-red-50 border border-red-200 text-red-900"
          }`}
        >
          <span className="text-lg leading-none mt-0.5">
            {alert.severity === "warning" ? "⚠️" : "🚨"}
          </span>
          <div>
            <span className="font-semibold">{alert.title}</span>
            {alert.body && <span className="font-normal ml-2 text-amber-800">{alert.body}</span>}
          </div>
        </div>
      ))}
    </div>
  )
}
