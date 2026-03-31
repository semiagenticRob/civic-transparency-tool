function ExternalLink({ href, children, className = "" }) {
  if (!href) return <span className={className}>{children}</span>
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={`hover:underline ${className}`}
    >
      {children}
    </a>
  )
}

export default function QuoteCard({ quote }) {
  const { speaker, quote: text, context, video_url, speaker_profile_url } = quote

  return (
    <div className="border-l-4 border-civic-500 pl-4 py-1">
      <blockquote className="text-sm text-gray-800 italic leading-relaxed mb-2">
        "{text}"
      </blockquote>

      <div className="flex items-center justify-between gap-3">
        <ExternalLink href={speaker_profile_url} className="text-xs font-semibold text-civic-600">
          — {speaker}
        </ExternalLink>

        {video_url && (
          <a
            href={video_url}
            target="_blank"
            rel="noreferrer"
            className="shrink-0 inline-flex items-center gap-1 text-xs text-gray-400 hover:text-civic-600 transition-colors"
            title="Watch in meeting video"
          >
            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="currentColor">
              <path d="M8 5v14l11-7z"/>
            </svg>
            Watch
          </a>
        )}
      </div>

      {context && (
        <p className="text-xs text-gray-500 mt-1">{context}</p>
      )}
    </div>
  )
}
