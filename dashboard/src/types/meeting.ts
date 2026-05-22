/**
 * Shape of the dashboard data payload produced by pipeline/save_dashboard_data.py
 * and consumed by App.jsx + the components under src/components/.
 *
 * Bump `EXPECTED_SCHEMA_VERSION` in App.jsx whenever the producer side bumps
 * SCHEMA_VERSION in pipeline/save_dashboard_data.py — see the runtime warning
 * in App.jsx for what happens on mismatch.
 *
 * This file is intentionally narrow: it types the fields the React app
 * actually reads, not every field the producer emits. The `type_specific`
 * block carries the full typed analysis; consumers can widen this type when
 * the dashboard starts rendering type-specific UI.
 */

export interface Alert {
  title: string;
  body: string;
  severity: 'info' | 'warning' | 'critical' | string;
  url: string | null;
}

export interface CouncilMember {
  name: string;
  title: string;
  district: string | null;
  profile_url: string | null;
}

export interface Quote {
  speaker: string;
  quote: string;
  context: string;
  timestamp_seconds: number | null;
  video_url: string | null;
  speaker_profile_url: string | null;
}

export interface Decision {
  motion: string;
  result: string;
  vote_breakdown: string;
  votes: Record<string, string>;
  significance: string;
}

export interface FeedItem {
  title: string;
  url: string | null;
}

export interface DashboardData {
  schema_version: number;
  city: string;
  state: string;
  meeting_date: string;
  generated_at: string;
  video_url: string | null;

  meeting_type: 'business' | 'workshop' | 'study_session' | string;
  meeting_purpose_blurb: string;
  lead_headline: string;
  schedule_portal_url: string | null;
  newsletter_subscribe_url: string | null;
  type_specific: unknown;

  meeting_summary: string;
  alerts: Alert[];
  key_decisions: Decision[];
  notable_quotes: Quote[];
  topics_discussed: string[];
  consistency_flags: string[];
  on_the_horizon: string;
  upcoming: FeedItem[];
  recent_news: FeedItem[];
  council_members: CouncilMember[];
}
