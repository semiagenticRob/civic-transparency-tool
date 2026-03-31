export default function QuoteCard({ quote }) {
  const { speaker, quote: text, context } = quote

  return (
    <div className="border-l-4 border-civic-500 pl-4 py-1">
      <blockquote className="text-sm text-gray-800 italic leading-relaxed mb-1">
        "{text}"
      </blockquote>
      <p className="text-xs font-semibold text-civic-600">— {speaker}</p>
      {context && (
        <p className="text-xs text-gray-500 mt-1">{context}</p>
      )}
    </div>
  )
}
