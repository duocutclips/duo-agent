export interface ApiErrorBody {
  code: string;
  message: string;
  hint?: string;
  detail?: string;
  errors?: string[];
}

export interface Campaign {
  id: string;
  name: string;
  slug: string;
  platforms: string[];
  game: string;
  url: string;
  payout_cpm: number | null;
  payout_notes: string;
  objective: string;
  requirements: string[];
  restrictions: string[];
  content_goals: string[];
  hook_examples: string[];
  reference_links: string[];
  codes: string[];
  notes: string;
  analysis: Analysis | null;
  documents?: CampaignDocument[];
  media_count?: number;
  project_count?: number;
  created_at: string;
  updated_at: string;
}

export interface CampaignDocument {
  id: string;
  kind: string;
  name: string;
  source: string;
  created_at: string;
  chars: number;
}

export interface AnalysisItem {
  category: string;
  text: string;
  status: "confirmed" | "suggestion";
  quote: string;
  rationale: string;
}

export interface Analysis {
  campaign_name: string;
  game: string;
  objective: string;
  target_audience: string;
  game_mechanics: string[];
  platforms: string[];
  recommended_min_seconds: number | null;
  recommended_max_seconds: number | null;
  length_is_confirmed: boolean;
  items: AnalysisItem[];
  generator: string;
  warning: string | null;
}

export interface Idea {
  id: string;
  campaign_id: string;
  position: number;
  category: string;
  title: string;
  hook: string;
  concept: string;
  script_angle: string;
  est_duration: number;
  required_gameplay: string[];
  cta: string;
  novelty_score: number;
  compliance_score: number;
  compliance_notes: string[];
  generator: string;
  selected: boolean;
}

export interface Script {
  id: string;
  idea_id: string | null;
  campaign_id: string;
  target_seconds: number;
  text: string;
  est_seconds: number;
  warnings: string[];
  generator: string;
  sentences?: string[];
  created_at: string;
  updated_at: string;
}

export interface Media {
  id: string;
  kind: "video" | "image" | "audio" | "sfx" | "music";
  path: string;
  filename: string;
  size: number;
  duration: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  has_audio: boolean;
  codec: string | null;
  audio_codec: string | null;
  orientation: string | null;
  thumbnail: string | null;
  category: string | null;
  tags: string[];
  license_note: string;
  campaign_id: string | null;
  analysis: MediaAnalysis | null;
  segment_count?: number;
  missing?: boolean;
  deduplicated?: boolean;
}

export interface MediaAnalysis {
  cuts: number[];
  black: [number, number][];
  static: [number, number][];
  silence: [number, number][];
  audio_peaks: number[];
  repeats: { first_start: number; first_end: number; repeat_start: number; repeat_end: number }[];
  motion_curve: number[];
  audio_curve: number[];
}

export interface Segment {
  id: string;
  media_id: string;
  start: number;
  end: number;
  label: string;
  kind: string;
  score: number;
  confidence: number;
  tags: string[];
  source: "auto" | "manual";
  enabled: boolean;
}

export interface VoiceProfile {
  id: string;
  name: string;
  provider: "system" | "elevenlabs";
  voice_id: string;
  settings: Record<string, number | string | boolean>;
  authorized: boolean;
  notes: string;
}

export interface Narration {
  id: string;
  script_id: string;
  provider: string;
  audio_path: string;
  duration: number;
  words: { word: string; start: number; end: number }[];
  alignment_method: string;
  cached?: boolean;
}

export interface TimelineItem {
  type: "video" | "zoom" | "fade" | "caption" | "text" | "image" | "narration" | "music" | "sfx";
  start?: number;
  end?: number;
  duration?: number;
  [key: string]: unknown;
}

export interface Timeline {
  version: 1;
  width: number;
  height: number;
  fps: number;
  duration: number;
  template_id?: string;
  seed?: number;
  warnings?: string[];
  items: TimelineItem[];
  [key: string]: unknown;
}

export interface QaCheck {
  name: string;
  status: "PASS" | "FAIL" | "N/A";
  detail: string;
}

export interface QaReport {
  overall: "READY" | "NOT READY";
  checks: QaCheck[];
  failed: string[];
}

export type ProjectStatus = "DRAFT" | "REVIEW" | "APPROVED" | "REJECTED" | "EXPORTED" | "POSTED" | "SUBMITTED";

export interface Stage {
  name: string;
  state: "done" | "current" | "todo";
}

export interface Project {
  id: string;
  campaign_id: string;
  idea_id: string | null;
  script_id: string | null;
  narration_id: string | null;
  template_id: string;
  title: string;
  status: ProjectStatus;
  media_ids: string[];
  music_id: string | null;
  timeline: Timeline | null;
  render_path: string | null;
  qa: QaReport | null;
  export_path: string | null;
  caption_text: string;
  hashtags: string[];
  seed: number;
  notes: string;
  history: { at: string; event: string; note?: string }[];
  stages: Stage[];
  ready: boolean;
  campaign?: Pick<Campaign, "id" | "name" | "slug" | "game" | "platforms">;
  idea?: Idea | null;
  script?: Script | null;
  narration?: Narration | null;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  kind: string;
  ref: string | null;
  status: "queued" | "running" | "succeeded" | "failed";
  message: string;
  progress: number;
  result: unknown;
  error: ApiErrorBody | null;
}

export interface Template {
  id: string;
  name: string;
  description?: string;
  builtin: boolean;
  overrides_builtin?: boolean;
  [key: string]: unknown;
}

export interface Submission {
  id: string;
  campaign_id: string;
  project_id: string | null;
  platform: string;
  post_url: string;
  submitted_at: string | null;
  status: string;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  saves: number;
  earnings: number | null;
  approved: number | null;
  notes: string;
  campaign_name?: string;
  estimated_earnings?: number | null;
  effective_cpm?: number | null;
  engagement_rate?: number | null;
  hook?: string | null;
  template_id?: string | null;
}

export interface Group {
  key: string;
  posts: number;
  total_views: number;
  avg_views: number;
}

export interface Analytics {
  totals: {
    posts: number;
    videos: number;
    views: number;
    likes: number;
    comments: number;
    shares: number;
    saves: number;
    earnings: number;
    avg_views_per_post: number;
    avg_views_per_video: number;
    effective_cpm: number | null;
  };
  best_hook: Group | null;
  best_template: Group | null;
  by_hook: Group[];
  by_template: Group[];
  by_category: Group[];
  sample_note: string | null;
  rows: Submission[];
}

export interface Dashboard {
  active_campaigns: number;
  videos_generated: number;
  videos_ready: number;
  videos_posted: number;
  total_views: number;
  estimated_earnings: number;
  recent_projects: { id: string; title: string; status: ProjectStatus; updated_at: string; template_id: string; ready: boolean }[];
}

export interface IntegrationStatus {
  ffmpeg: Record<string, { available: boolean; path: string; version?: string }>;
  llm: { configured: boolean; model: string; message: string | null };
  voice: { elevenlabs: { configured: boolean; message: string | null }; system: { available: boolean; engine: string; message: string | null } };
  transcription: { whisper_api: { configured: boolean; message: string | null }; faster_whisper: { installed: boolean }; fallback: string };
  publishing: { manual: { configured: boolean }; youtube: { configured: boolean; message: string | null } };
}

export interface PublishKit {
  caption: string;
  hashtags: string[];
  hashtags_text: string;
  platforms: { name: string; url: string }[];
  file: string | null;
  campaign_url: string;
  status: ProjectStatus;
}
