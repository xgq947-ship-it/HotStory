export type TopicStatus =
  | "CREATED"
  | "PLANNING"
  | "SEARCHING"
  | "FETCHING"
  | "EXTRACTING"
  | "CLUSTERING"
  | "VERIFYING"
  | "TIMELINE"
  | "STORY"
  | "VALUE"
  | "WRITING"
  | "REVIEWING"
  | "DIRECTING"
  | "COMPLETED"
  | "FAILED";

export interface Topic {
  id: string;
  title: string;
  input_mode: string;
  status: TopicStatus;
  current_step: string | null;
  error: string | null;
  requested_duration: 60 | 90 | 180;
  research_depth: number;
  created_at: string;
  updated_at: string;
}

export interface StepStatus {
  step: string;
  status: "PENDING" | "RUNNING" | "SUCCESS" | "FAILED";
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  retry_count: number;
}

export interface StatusPayload {
  topic: Topic;
  steps: StepStatus[];
  counts: Record<string, number>;
  material_ready: boolean;
  minimums: Record<string, number>;
  /** artifact kind -> version，用来判断要不要重新拉取，而不是每轮全量拉 */
  artifact_versions: Record<string, number>;
}

export interface Hotspot {
  title: string;
  platform: string;
  rank: number;
  heat: number | string;
  url: string;
  summary: string;
  story_score: number;
}

export interface Source {
  id: string;
  title: string;
  url: string;
  publisher: string;
  published_at: string;
  author: string;
  language: string;
  snippet: string;
  credibility_score: number;
  fetch_status: string;
  crawler: string;
  fetch_error?: string | null;
}

export interface Fact {
  id: string;
  statement: string;
  fact_type: string;
  date: string;
  people: string[];
  organizations: string[];
  locations: string[];
  numbers: string[];
  source_ids: string[];
  confidence: number;
  verification_status: string;
  verified: boolean;
  sensitive: boolean;
}

export interface Event {
  id: string;
  title: string;
  summary: string;
  date: string;
  event_type: string;
  fact_ids: string[];
  source_ids: string[];
  people: string[];
  emotion: string[];
  confidence: number;
}

export interface TimelineItem {
  date: string;
  title: string;
  description: string;
  event_ids: string[];
  importance: number;
}

export interface TimelinePayload {
  timeline: TimelineItem[];
}

export interface StoryPayload {
  central_theme: string;
  core_conflict: string;
  story_arc: Array<{ stage: string; event_ids: string[] }>;
  selected_events: string[];
  selected_cases: string[];
  selected_data: string[];
}

export interface ScriptPayload {
  script: string;
  review: { score: number; issues: string[]; passed: boolean; rewrite_count?: number } | null;
}

export interface CharacterImageSettings {
  model: string;
  aspect_ratio: string;
  quality: string;
  consistency: string;
}

export interface CharacterAsset {
  id: string;
  reference_token: string;
  prompt_label: string;
  role: "lead" | "supporting";
  story_function: string;
  source_fact_ids: string[];
  visual_anchor: string;
  wardrobe_anchor: string;
  image_prompt: string;
  acting_profile: string;
  voice_prompt: string;
  default_use_reference: boolean;
  identity_basis: "verified_role_visualization";
  disclosure: string;
  image_settings: CharacterImageSettings;
  optimized_by: string;
}

export interface CinematicShot {
  shot_id: string;
  title: string;
  start_second: number;
  end_second: number;
  duration_seconds: number;
  narration: string;
  dialogue: string;
  visual_brief: string;
  active_character_ids: string[];
  event_ids: string[];
  source_ids: string[];
  prompt_body_template: string;
  ambient_audio: string;
  target_model: string;
  optimized_by: string;
  revision: number;
}

export interface SkillStage {
  order: number;
  skill: string;
  purpose: string;
  instruction_mode: "verbatim";
  source_sha256: string;
}

export interface ProductionPackage {
  version: string;
  topic_id: string;
  generated_at: string;
  duration_seconds: number;
  llm_profile?: string;
  max_shot_duration_seconds: 10;
  generation_mode: "ai_optimized" | "mixed" | "fallback";
  warnings: string[];
  prompt_preservation: "lossless";
  style_bible: string;
  skills: SkillStage[];
  characters: CharacterAsset[];
  shots: CinematicShot[];
}

export interface HealthPayload {
  status: string;
  llm_provider: string;
  llm_ready: boolean;
  search_provider: string;
  crawler_provider: string;
  version: string;
  /** 只有请求 /health?probe=true 时才有值 */
  llm_probe_ok?: boolean | null;
  llm_probe_error?: string | null;
}
