import { useState, useEffect } from "react"
import AlertBanner from "./components/AlertBanner"
import MeetingSummary from "./components/MeetingSummary"
import VoteCard from "./components/VoteCard"
import QuoteCard from "./components/QuoteCard"
import CouncilGrid from "./components/CouncilGrid"
import Sidebar from "./components/Sidebar"

const CITY = "arvada"

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`/data/${CITY}/latest.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch((e) => setError(e.message))
  }, [])

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-500 text-sm">
        Failed to load data: {error}
      </div>
    )
  }

  if (!data) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-400 text-sm">
        Loading…
      </div>
    )
  }

  const updatedAt = new Date(data.generated_at).toLocaleDateString("en-US", {
    month: "long", day: "numeric", year: "numeric",
  })

  return (
    <div className="min-h-screen bg-gray-50 font-sans">

      {/* Header */}
      <header className="bg-civic-900 text-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between gap-4">
          <div>
            <h1 className="text-lg font-bold tracking-tight">
              {data.city} City Watch
            </h1>
            <p className="text-civic-100 text-xs mt-0.5">
              {data.city}, {data.state} · Updated {updatedAt}
            </p>
          </div>
          <a
            href="#subscribe"
            className="shrink-0 bg-civic-500 hover:bg-civic-600 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
          >
            Subscribe →
          </a>
        </div>
      </header>

      {/* Main */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        <AlertBanner alerts={data.alerts} />

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

          {/* Left: main content */}
          <div className="lg:col-span-2 space-y-8">

            {/* Meeting summary */}
            <MeetingSummary
              summary={data.meeting_summary}
              date={data.meeting_date}
              topics={data.topics_discussed}
              videoUrl={data.video_url}
            />

            {/* Votes */}
            <section>
              <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-4">
                How They Voted
              </h2>
              <div className="space-y-4">
                {data.key_decisions?.map((d, i) => (
                  <VoteCard key={i} decision={d} />
                ))}
              </div>
            </section>

            {/* Quotes */}
            {data.notable_quotes?.length > 0 && (
              <section>
                <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-4">
                  What They Said
                </h2>
                <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm space-y-6">
                  {data.notable_quotes.map((q, i) => (
                    <QuoteCard key={i} quote={q} />
                  ))}
                </div>
              </section>
            )}

            {/* Council members */}
            <section>
              <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-4">
                The Council
              </h2>
              <CouncilGrid members={data.council_members} decisions={data.key_decisions} />
            </section>

          </div>

          {/* Right: sidebar */}
          <div className="lg:col-span-1">
            <Sidebar
              upcoming={data.upcoming}
              recentNews={data.recent_news}
              consistencyFlags={data.consistency_flags}
            />
          </div>

        </div>

        {/* Subscribe CTA */}
        <div id="subscribe" className="mt-12 bg-civic-900 rounded-2xl p-8 text-center text-white">
          <h3 className="text-xl font-bold mb-2">Stay in the loop</h3>
          <p className="text-civic-100 text-sm mb-6 max-w-md mx-auto">
            Get a plain-English summary of every {data.city} City Council meeting delivered to your inbox — written by a local, powered by AI.
          </p>
          <a
            href="https://beehiiv.com"
            target="_blank"
            rel="noreferrer"
            className="inline-block bg-white text-civic-900 font-semibold text-sm px-6 py-3 rounded-lg hover:bg-civic-50 transition-colors"
          >
            Subscribe to the newsletter
          </a>
        </div>

      </main>

      <footer className="text-center text-xs text-gray-400 py-8">
        {data.city} City Watch · Independent, AI-assisted civic journalism · Not affiliated with the City of {data.city}
      </footer>
    </div>
  )
}
