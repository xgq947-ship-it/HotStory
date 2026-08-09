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
  narrative_mode?: "cinematic_human_story" | "factual_documentary";
  generation_mode?: "ai_generated" | "deterministic_fallback";
  generation_note?: string;
  protagonist_event_id?: string;
  dramatic_question?: string;
  ending_device?: string;
  quality?: NarrativeQuality;
  beats?: StoryBeat[];
  story_arc: Array<{ stage: string; event_ids: string[] }>;
  selected_events: string[];
  selected_cases: string[];
  selected_data: string[];
}

export interface NarrativeQuality {
  score: number;
  issues: string[];
  passed: boolean;
}

export interface StoryBeat {
  beat_id: string;
  narrative_function: string;
  objective: string;
  obstacle: string;
  stakes: string;
  tactic: string;
  turn: string;
  value_before: string;
  value_after: string;
  cause_link: string;
  causal_basis: "verified" | "editorial_transition";
  dramatization_mode: "verified_observation" | "composite_reenactment" | "archive_or_data";
  visual_action: string;
  event_ids: string[];
  source_ids: string[];
  intensity: number;
}

export interface ScriptPayload {
  script: string;
  review: {
    score: number;
    issues: string[];
    passed: boolean;
    rewrite_count?: number;
    fallback_used?: boolean;
    script_generation_mode?: "ai_generated" | "deterministic_fallback" | "legacy";
    generation_reason?: string;
    causality_score?: number;
    rhythm_score?: number;
    ending_score?: number;
    narration_fit_score?: number;
  } | null;
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

export interface InternalShot {
  internal_shot_id: string;
  start_offset_seconds: number;
  end_offset_seconds: number;
  shot_size: "EWS" | "WS" | "MS" | "MCU" | "CU" | "ECU" | "INSERT";
  fov_degrees: 8 | 12 | 18 | 29 | 47 | 63 | 84 | 107;
  visual_action: string;
  camera: string;
  performance: string;
  entry_state: string;
  exit_state: string;
  cut_in:
    | "START"
    | "HARD CUT"
    | "SMASH CUT"
    | "MATCH CUT"
    | "INSERT CUT"
    | "REVERSE CUT"
    | "WHIP CUT";
  cut_motivation: string;
  intensity: number;
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
  sequence_id: string;
  beat_id: string;
  beat_ids: string[];
  narrative_function: string;
  objective: string;
  obstacle: string;
  stakes: string;
  tactic: string;
  beat_changes: string[];
  entry_state: string;
  exit_state: string;
  value_before: string;
  value_after: string;
  cause_link: string;
  cut_motivation: string;
  audio_bridge: string;
  intensity: number;
  format_mode: "single_take" | "controlled_multishot";
  internal_shots: InternalShot[];
  prompt_body_template: string;
  ambient_audio: string;
  target_model: string;
  optimized_by: string;
  revision: number;
}

export interface AudioCue {
  start_second: number;
  end_second: number;
  layer: "score" | "silence" | "ambient_bridge";
  description: string;
}

export interface GlobalAudioPlan {
  score_arc: string;
  music_rule: string;
  silence_points: number[];
  cues: AudioCue[];
}

export interface AnimaticCheck {
  passed: boolean;
  score: number;
  generation_unit_count: number;
  internal_shot_count: number;
  shot_count: number;
  sequence_count: number;
  total_duration_seconds: number;
  average_shot_duration_seconds: number;
  average_internal_shot_duration_seconds: number;
  rhythm_curve: number[];
  issues: string[];
}

export interface ProductionReadiness {
  passed: boolean;
  score: number;
  blockers: string[];
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
  generation_strategy: "fast_multishot";
  generation_unit_duration_seconds: 10;
  generation_unit_count: number;
  internal_shot_count: number;
  narrative_mode: "cinematic_human_story" | "factual_documentary";
  story_generation_mode: "ai_generated" | "deterministic_fallback" | "legacy";
  script_generation_mode: "ai_generated" | "deterministic_fallback" | "legacy";
  generation_mode: "ai_optimized" | "mixed" | "fallback";
  ready_for_generation: boolean;
  readiness: ProductionReadiness;
  narrative_quality: NarrativeQuality;
  animatic: AnimaticCheck;
  audio_plan: GlobalAudioPlan;
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

export interface SettingFieldState {
  name: string;
  label: string;
  group: string;
  kind: "text" | "password" | "number" | "boolean" | "select";
  secret: boolean;
  options: string[];
  help: string;
  placeholder: string;
  restart_required: boolean;
  editable: boolean;
  /** [字段名, "值1|值2"]：目标字段取到其中一个值时才显示本项 */
  depends_on: [string, string] | null;
  value: string | number | boolean | null;
  configured: boolean;
  source: "manual" | "env" | "env_file" | "default";
}

export interface SettingsPayload {
  groups: Record<string, string>;
  fields: SettingFieldState[];
  version: string;
  repository_url: string;
}

export interface CodexStatus {
  available: boolean;
  path: string;
  version: string;
  error: string;
  searched: string[];
}

export interface ReleaseInfo {
  tag_name: string;
  name: string;
  html_url: string;
  body: string;
  published_at: string;
}

export interface UpdateCheckPayload {
  current_version: string;
  latest: ReleaseInfo | null;
  update_available: boolean;
  releases: ReleaseInfo[];
  error: string;
}
