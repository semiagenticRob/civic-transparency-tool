const VOTE_STYLE = {
  Yes:     { icon: "✓", cls: "bg-green-100 text-green-800 border-green-200" },
  No:      { icon: "✗", cls: "bg-red-100 text-red-800 border-red-200" },
  Abstain: { icon: "—", cls: "bg-gray-100 text-gray-600 border-gray-200" },
  Absent:  { icon: "·", cls: "bg-gray-50 text-gray-400 border-gray-100" },
}

const RESULT_STYLE = {
  Passed: "bg-green-100 text-green-800",
  Failed: "bg-red-100 text-red-800",
  Tabled: "bg-amber-100 text-amber-800",
}

export default function VoteCard({ decision }) {
  const { motion, result, vote_breakdown, votes, significance } = decision
  const resultStyle = RESULT_STYLE[result] || "bg-gray-100 text-gray-700"

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3 mb-3">
        <h3 className="text-sm font-semibold text-gray-900 leading-snug flex-1">{motion}</h3>
        <div className="flex flex-col items-end gap-1 shrink-0">
          <span className={`text-xs font-bold px-2.5 py-1 rounded-full ${resultStyle}`}>
            {result}
          </span>
          {vote_breakdown && (
            <span className="text-xs text-gray-400 font-medium">{vote_breakdown}</span>
          )}
        </div>
      </div>

      {votes && Object.keys(votes).length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {Object.entries(votes).map(([member, vote]) => {
            const style = VOTE_STYLE[vote] || VOTE_STYLE.Abstain
            const lastName = member.split(" ").slice(-1)[0]
            return (
              <span
                key={member}
                title={`${member}: ${vote}`}
                className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded border ${style.cls}`}
              >
                <span className="font-bold">{style.icon}</span>
                {lastName}
              </span>
            )
          })}
        </div>
      )}

      {significance && (
        <p className="text-xs text-gray-500 leading-relaxed border-t border-gray-100 pt-3">
          {significance}
        </p>
      )}
    </div>
  )
}
