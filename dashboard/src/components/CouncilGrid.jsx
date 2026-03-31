function initials(name) {
  return name.split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase()
}

function MemberCard({ member, votes }) {
  const yeas  = Object.values(votes).filter((v) => v === "Yes").length
  const nays  = Object.values(votes).filter((v) => v === "No").length
  const total = yeas + nays

  const memberVote = votes[member.name]
  const voteColor = {
    Yes: "bg-green-100 text-green-800",
    No:  "bg-red-100 text-red-800",
  }[memberVote] || "bg-gray-100 text-gray-500"

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm flex flex-col gap-2">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-civic-500 flex items-center justify-center text-white text-sm font-bold shrink-0">
          {initials(member.name)}
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900 truncate">{member.name}</p>
          <p className="text-xs text-gray-500 truncate">
            {member.title}{member.district ? ` · ${member.district}` : ""}
          </p>
        </div>
      </div>
      {memberVote && (
        <span className={`self-start text-xs font-semibold px-2 py-0.5 rounded-full ${voteColor}`}>
          Last vote: {memberVote}
        </span>
      )}
    </div>
  )
}

export default function CouncilGrid({ members, decisions }) {
  // Aggregate all votes across decisions into a single map of name → last vote
  const aggregateVotes = {}
  decisions?.forEach((d) => {
    if (d.votes) Object.assign(aggregateVotes, d.votes)
  })

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400 mb-4">
        Council Members
      </h2>
      <div className="grid grid-cols-1 gap-3">
        {members.map((m) => (
          <MemberCard key={m.name} member={m} votes={aggregateVotes} />
        ))}
      </div>
    </div>
  )
}
