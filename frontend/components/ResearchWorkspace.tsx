"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

import { ApiError, api, apiConditional, scriptDownloadUrl } from "@/lib/api";
import { copyTextToClipboard } from "@/lib/clipboard";
import { stepLabels } from "@/lib/pipeline";
import type {
  Event,
  Fact,
  ProductionMode,
  ProductionPackage,
  ScriptPayload,
  Source,
  StatusPayload,
  StoryPayload,
  TimelinePayload,
} from "@/lib/types";

import { Brand } from "./Brand";
import { ProductionWorkspace } from "./ProductionWorkspace";
import { SettingsDialog } from "./SettingsDialog";
import { StatusPill } from "./StatusPill";

const tabs = ["概览", "时间线", "案例", "数据", "来源", "剧本", "影视生成"] as const;
type Tab = (typeof tabs)[number];

function confidenceLabel(value: number) {
  if (value >= 0.85) return "高";
  if (value >= 0.7) return "中";
  return "待核验";
}

function formatDate(value: string) {
  if (!value) return "日期未明确";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "short", day: "numeric" }).format(parsed);
}

const POLL_INTERVAL_MS = 2500;

/** 每格盖一个读数：完成盖耗时，运行中盖 RUN，失败盖 ERR。 */
function stepReadout(step: StatusPayload["steps"][number]): string {
  if (step.status === "SUCCESS") {
    if (step.started_at && step.completed_at) {
      const seconds = Math.max(
        0,
        Math.round(
          (new Date(step.completed_at).getTime() - new Date(step.started_at).getTime()) / 1000,
        ),
      );
      const minutes = Math.floor(seconds / 60);
      return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
    }
    return "OK";
  }
  if (step.status === "RUNNING") return "RUN";
  if (step.status === "FAILED") return "ERR";
  return "—";
}

/**
 * 每个 artifact 的"变没变"信号。以前每 2.5 秒把 7 个接口全量拉一遍
 * （实测 419 秒里 1188 次请求、每轮约 390KB），现在只在信号变化时拉。
 * DB 派生的 sources/facts/events 没有版本号，用相关步骤的状态当信号。
 */
function artifactKeys(status: StatusPayload | null): Record<string, string> {
  if (!status) return {};
  const stepStatus = (name: string) =>
    status.steps.find((step) => step.step === name)?.status ?? "PENDING";
  const version = (kind: string) => String(status.artifact_versions?.[kind] ?? 0);
  return {
    sources: [stepStatus("search"), stepStatus("fetch"), stepStatus("verify")].join("/"),
    facts: [stepStatus("extract"), stepStatus("verify")].join("/"),
    events: [stepStatus("cluster"), stepStatus("verify")].join("/"),
    timeline: version("timeline"),
    story: version("story_arc"),
    script: version("script") + "/" + version("review"),
    production: version("production_package"),
  };
}

function Metric({ label, value, target }: { label: string; value: number; target?: number }) {
  const reached = target === undefined || value >= target;
  return (
    <div className="rounded-2xl bg-paper-2 p-4 ring-1 ring-rule">
      <div className="flex items-baseline gap-1.5">
        <span className="text-2xl font-semibold tracking-[-0.04em] tabular-nums">{value}</span>
        {target !== undefined ? <span className="text-xs text-ink-3">/ {target}</span> : null}
      </div>
      <div className="mt-1.5 flex items-center gap-1.5 text-xs text-ink-2">
        <span className={`size-1.5 rounded-full ${reached ? "bg-verified" : "bg-pending"}`} />
        {label}
      </div>
    </div>
  );
}

export function ResearchWorkspace({ topicId }: { topicId: string }) {
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [timeline, setTimeline] = useState<TimelinePayload | null>(null);
  const [story, setStory] = useState<StoryPayload | null>(null);
  const [script, setScript] = useState<ScriptPayload | null>(null);
  const [production, setProduction] = useState<ProductionPackage | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("概览");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const fetchedKeys = useRef<Record<string, string>>({});
  const etags = useRef<Record<string, string | null>>({});
  const inFlight = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    // 上一轮还没回来就跳过这一轮，否则后端一慢请求就无限叠加。
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const nextStatus = await api<StatusPayload>(`/topics/${topicId}/status`);
      setStatus(nextStatus);
      setError(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "无法连接本地 HotStory 服务。 ");
    } finally {
      inFlight.current = false;
    }
  }, [topicId]);

  const forceRefresh = useCallback(async () => {
    fetchedKeys.current = {};
    etags.current = {};
    await refresh();
  }, [refresh]);

  useEffect(() => {
    fetchedKeys.current = {};
    etags.current = {};
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const terminal = status?.topic.status === "COMPLETED" || status?.topic.status === "FAILED";
    if (terminal) return;
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh, status?.topic.status]);

  // artifact 只在信号变化时拉一次。abort 只在卸载/换主题时触发——
  // 如果每次 status 更新都 abort，慢接口（sources 是最大的一个）会永远拉不完。
  useEffect(() => {
    const controller = new AbortController();
    abortRef.current = controller;
    return () => {
      controller.abort();
      abortRef.current = null;
    };
  }, [topicId]);

  useEffect(() => {
    if (!status) return;
    const keys = artifactKeys(status);

    async function load<T>(
      name: string,
      path: string,
      apply: (value: T) => void,
      conditional = false,
    ) {
      if (keys[name] === fetchedKeys.current[name]) return;
      // 先占位，避免下一轮 status 更新时重复发同一个请求。
      fetchedKeys.current[name] = keys[name];
      try {
        if (conditional) {
          const result = await apiConditional<T>(path, etags.current[name] ?? null, {
            signal: abortRef.current?.signal,
          });
          etags.current[name] = result.etag;
          if (result.data !== null) apply(result.data);
        } else {
          apply(await api<T>(path, { signal: abortRef.current?.signal }));
        }
      } catch (cause) {
        // 404 说明这个 artifact 还没生成——对当前信号来说这就是正确答案，
        // 保留占位，等信号变化再试。撤掉占位会让未生成的 artifact 每轮都重发一次。
        if (!(cause instanceof ApiError && cause.status === 404)) {
          delete fetchedKeys.current[name];
        }
      }
    }

    void Promise.all([
      load<Source[]>("sources", `/topics/${topicId}/sources`, setSources),
      load<Fact[]>("facts", `/topics/${topicId}/facts`, setFacts),
      load<Event[]>("events", `/topics/${topicId}/events`, setEvents),
      load<TimelinePayload>("timeline", `/topics/${topicId}/timeline`, setTimeline, true),
      load<StoryPayload>("story", `/topics/${topicId}/story`, setStory, true),
      load<ScriptPayload>("script", `/topics/${topicId}/script`, setScript, true),
      load<ProductionPackage>(
        "production",
        `/topics/${topicId}/production-package`,
        setProduction,
        true,
      ),
    ]);
  }, [status, topicId]);

  const sourceMap = useMemo(
    () => new Map(sources.map((source) => [source.id, source])),
    [sources],
  );
  const eventMap = useMemo(() => new Map(events.map((event) => [event.id, event])), [events]);
  const cases = facts.filter((fact) => fact.fact_type === "PERSONAL_CASE" && fact.verified);
  const dataFacts = facts.filter((fact) => fact.fact_type === "DATA" && fact.verified);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      await api(`/topics/${topicId}/research`, {
        method: "POST",
        body: JSON.stringify({ duration: status?.topic.requested_duration ?? 90 }),
      });
      await forceRefresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "启动失败");
    } finally {
      setBusy(false);
    }
  }

  async function continueResearch() {
    setBusy(true);
    setError(null);
    try {
      await api(`/topics/${topicId}/continue`, { method: "POST", body: "{}" });
      await forceRefresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "继续研究失败");
    } finally {
      setBusy(false);
    }
  }

  async function rewrite(duration: 60 | 90 | 180) {
    setBusy(true);
    setError(null);
    try {
      await api(`/topics/${topicId}/rewrite-script`, {
        method: "POST",
        body: JSON.stringify({ duration }),
      });
      setActiveTab("概览");
      await forceRefresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "重新生成失败");
    } finally {
      setBusy(false);
    }
  }

  async function copyScript() {
    if (!script?.script) return;
    try {
      await copyTextToClipboard(script.script);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "复制失败");
    }
  }

  async function generateProduction(mode: ProductionMode = "resume") {
    setBusy(true);
    setError(null);
    setActiveTab("影视生成");
    try {
      await api(`/topics/${topicId}/production-package`, {
        method: "POST",
        body: JSON.stringify({ mode }),
      });
      await forceRefresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "影视生成包启动失败");
    } finally {
      setBusy(false);
    }
  }

  async function regenerateProductionShot(
    shotId: string,
    currentPrompt: string,
  ): Promise<ProductionPackage> {
    setError(null);
    try {
      const next = await api<ProductionPackage>(
        `/topics/${topicId}/production-package/shots/${shotId}/regenerate`,
        {
          method: "POST",
          body: JSON.stringify({ current_prompt: currentPrompt }),
        },
      );
      setProduction(next);
      return next;
    } catch (cause) {
      const message = cause instanceof ApiError ? cause.message : "当前镜头重新优化失败";
      setError(message);
      throw new Error(message);
    }
  }

  if (!status) {
    return (
      <div className="grid min-h-screen place-items-center bg-[#f5f5f7]">
        <div className="text-center">
          <div className="mx-auto size-7 animate-spin rounded-full border-2 border-rule border-t-ink" />
          <p className="mt-4 text-sm text-ink-2">正在打开研究档案…</p>
          {error ? <p className="mt-2 text-sm text-pending">{error}</p> : null}
        </div>
      </div>
    );
  }

  const topic = status.topic;
  const isRunning = !["CREATED", "COMPLETED", "FAILED"].includes(topic.status);

  return (
    <div className="min-h-screen">
      <header className="bench-nav sticky top-0 z-30">
        <div className="mx-auto flex h-14 max-w-[1280px] items-center justify-between gap-5 px-5 sm:px-8">
          <div className="flex min-w-0 items-center gap-4">
            <Brand />
            <span className="hidden h-4 w-px bg-rule sm:block" />
            <span className="hidden max-w-[420px] truncate text-[13px] text-ink-2 sm:block">
              {topic.title}
            </span>
          </div>
          <div className="flex items-center gap-4">
            <StatusPill status={topic.status} />
            <button
              className="gauge rounded-2xl border border-rule px-2.5 py-1.5 text-ink-2 transition hover:border-ink hover:text-ink"
              onClick={() => setSettingsOpen(true)}
            >
              设置
            </button>
            <Link className="gauge text-ink-3 transition hover:text-ink" href="/">
              关闭
            </Link>
          </div>
        </div>
      </header>

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />

      <main className="mx-auto max-w-[1280px] px-5 pb-24 pt-9 sm:px-8 sm:pt-12">
        <div className="grid gap-8 lg:grid-cols-[290px_minmax(0,1fr)]">
          <aside className="space-y-5 lg:sticky lg:top-20 lg:self-start">
            <section className="sheet rounded-2xl p-5">
              <p className="label">RESEARCH FILE</p>
              <h1 className="mt-2.5 text-[19px] font-semibold leading-[1.4] tracking-[-0.025em]">
                {topic.title}
              </h1>
              <p className="gauge mt-2.5 text-ink-3">
                {formatDate(topic.created_at)} · 深挖 {topic.research_depth} 次
              </p>

              {error || topic.error ? (
                <p className="mt-3 border-l-2 border-pending bg-pending/[0.07] px-3 py-2.5 text-[12.5px] leading-[1.6]">
                  {error ?? topic.error}
                </p>
              ) : null}

              {topic.status === "CREATED" ? (
                <button
                  className="mt-4 w-full rounded-xl border border-ink bg-ink px-4 py-2.5 text-[13px] font-medium text-paper transition hover:bg-ink-2 disabled:border-rule disabled:bg-transparent disabled:text-ink-3"
                  onClick={() => void start()}
                  disabled={busy}
                  type="button"
                >
                  开始深度研究
                </button>
              ) : null}
              {topic.status === "FAILED" ? (
                <button
                  className="mt-4 w-full rounded-xl border border-ink bg-ink px-4 py-2.5 text-[13px] font-medium text-paper transition hover:bg-ink-2 disabled:border-rule disabled:bg-transparent disabled:text-ink-3"
                  onClick={() => void continueResearch()}
                  disabled={busy}
                  type="button"
                >
                  {busy ? "正在恢复…" : "继续深挖"}
                </button>
              ) : null}
            </section>

            {/* 证据链轨道：13 步排成片头引带，完成的格子盖上耗时。 */}
            <section className="sheet rounded-2xl p-5">
              <div className="flex items-baseline justify-between">
                <h2 className="text-sm font-semibold">研究进度</h2>
                <span className="gauge text-ink-3">
                  {status.steps.filter((step) => step.status === "SUCCESS").length}/
                  {status.steps.length}
                </span>
              </div>
              <ol className="leader mt-3">
                {status.steps.map((step) => (
                  <li className="frame" data-state={step.status} key={step.step}>
                    <span className="flex items-center gap-2.5">
                      <span className="step-dot">
                        {step.status === "FAILED" ? "!" : step.status === "RUNNING" ? "•" : "✓"}
                      </span>
                      <span
                        className={`text-[13px] leading-[1.4] ${
                          step.status === "PENDING" ? "text-ink-3" : "text-ink"
                        }`}
                      >
                        {stepLabels[step.step] ?? step.step}
                      </span>
                    </span>
                    <span className="gauge text-ink-3">{stepReadout(step)}</span>
                  </li>
                ))}
              </ol>
            </section>
          </aside>

          <div className="min-w-0">
            <section className="sheet rounded-2xl">
              <nav className="overflow-x-auto border-b border-rule px-1.5" aria-label="研究档案导航">
                <div className="flex min-w-max">
                  {tabs.map((tab) => (
                    <button
                      className={`relative px-3.5 py-3 text-[13px] transition ${
                        activeTab === tab ? "font-semibold text-ink" : "text-ink-3 hover:text-ink-2"
                      }`}
                      key={tab}
                      onClick={() => setActiveTab(tab)}
                      type="button"
                    >
                      {tab}
                      {activeTab === tab ? (
                        <span className="absolute inset-x-2.5 -bottom-px h-0.5 bg-ink" />
                      ) : null}
                    </button>
                  ))}
                </div>
              </nav>

              <div className="p-5 sm:p-7 lg:p-8">
                {activeTab === "概览" ? (
                  <Overview
                    status={status}
                    story={story}
                    events={events}
                    isRunning={isRunning}
                  />
                ) : null}
                {activeTab === "时间线" ? <TimelineView timeline={timeline} eventMap={eventMap} /> : null}
                {activeTab === "案例" ? <CasesView cases={cases} sourceMap={sourceMap} /> : null}
                {activeTab === "数据" ? <DataView facts={dataFacts} sourceMap={sourceMap} /> : null}
                {activeTab === "来源" ? <SourcesView sources={sources} facts={facts} /> : null}
                {activeTab === "剧本" ? (
                  <ScriptView
                    topicId={topicId}
                    payload={script}
                    busy={busy}
                    copied={copied}
                    onCopy={() => void copyScript()}
                    onRewrite={(duration) => void rewrite(duration)}
                  />
                ) : null}
                {activeTab === "影视生成" ? (
                  <ProductionWorkspace
                    topicId={topicId}
                    payload={production}
                    scriptReady={Boolean(script?.script)}
                    busy={busy}
                    isRunning={isRunning}
                    onGenerate={generateProduction}
                    onRegenerateShot={regenerateProductionShot}
                  />
                ) : null}
              </div>
            </section>
          </div>
        </div>
      </main>
    </div>
  );
}

function Overview({
  status,
  story,
  events,
  isRunning,
}: {
  status: StatusPayload;
  story: StoryPayload | null;
  events: Event[];
  isRunning: boolean;
}) {
  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-3">Evidence dashboard</p>
          <h2 className="mt-2 text-[30px] font-semibold tracking-[-0.045em]">研究概览</h2>
        </div>
        {isRunning ? <p className="text-xs text-verified">数据会随研究进度自动更新</p> : null}
      </div>

      <div className="mt-7 grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Metric
          label="有效来源"
          value={status.counts.valid_sources ?? 0}
          target={status.minimums.valid_sources}
        />
        <Metric
          label="已核验事实"
          value={status.counts.verified_facts ?? 0}
          target={status.minimums.verified_facts}
        />
        <Metric
          label="真实案例"
          value={status.counts.personal_cases ?? 0}
          target={status.minimums.personal_cases}
        />
        <Metric label="关键数据" value={status.counts.key_data ?? 0} target={status.minimums.key_data} />
      </div>

      {story ? (
        <div className="mt-8 grid gap-4 md:grid-cols-2">
          <div className="rounded-2xl bg-ink p-6 text-paper">
            <div className="flex items-center justify-between gap-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-3">Central theme</p>
              {story.quality ? (
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${story.quality.passed ? "bg-verified/20 text-verified" : "bg-pending/20 text-pending"}`}>
                  故事 {story.quality.score} 分
                </span>
              ) : null}
            </div>
            <h3 className="mt-3 text-[22px] font-semibold leading-8 tracking-[-0.03em]">{story.central_theme}</h3>
            <p className="mt-4 text-sm leading-6 text-ink-3">核心冲突：{story.core_conflict}</p>
            {story.dramatic_question ? <p className="mt-2 text-sm leading-6 text-ink-3">戏剧问题：{story.dramatic_question}</p> : null}
            {story.generation_mode === "deterministic_fallback" ? (
              <p className="mt-3 text-xs leading-5 text-amber-300">当前故事为确定性保底结构，不能进入成片就绪状态。</p>
            ) : null}
          </div>
          <div className="rounded-2xl bg-paper-2 p-6 ring-1 ring-rule">
            <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-3">Story arc</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {(story.beats?.length ? story.beats : story.story_arc).map((stage, index) => (
                <span className="rounded-full bg-card px-3 py-1.5 text-xs font-medium ring-1 ring-rule" key={`${"beat_id" in stage ? stage.beat_id : stage.stage}-${index}`}>
                  {"narrative_function" in stage ? `${stage.narrative_function} · ${stage.intensity}` : stage.stage}
                </span>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="mt-8 rounded-2xl border border-dashed border-rule px-6 py-12 text-center text-sm text-ink-3">
          {isRunning ? "故事主线会在事实与时间线核验完成后出现。" : "尚未生成故事主线。"}
        </div>
      )}

      {events.length ? (
        <div className="mt-8">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold">代表事件</h3>
            <span className="text-xs text-ink-3">共 {events.length} 个</span>
          </div>
          <div className="divide-y divide-rule rounded-2xl ring-1 ring-rule">
            {events.slice(0, 5).map((event) => (
              <div className="grid gap-1 px-4 py-3.5 sm:grid-cols-[90px_1fr]" key={event.id}>
                <span className="text-xs tabular-nums text-ink-3">{event.date || "时间待定"}</span>
                <div>
                  <p className="text-sm font-medium">{event.title}</p>
                  <p className="mt-1 line-clamp-2 text-xs leading-5 text-ink-2">{event.summary}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TimelineView({ timeline, eventMap }: { timeline: TimelinePayload | null; eventMap: Map<string, Event> }) {
  if (!timeline?.timeline.length) return <Empty message="时间线尚未生成。" />;
  return (
    <div>
      <SectionTitle eyebrow="Chronology" title="时间线" note={`${timeline.timeline.length} 个关键节点`} />
      <ol className="relative mt-9 space-y-0 before:absolute before:bottom-4 before:left-[7px] before:top-3 before:w-px before:bg-rule">
        {timeline.timeline.map((item, index) => (
          <li className="relative grid gap-3 pb-8 pl-9 sm:grid-cols-[120px_1fr] sm:gap-5" key={`${item.date}-${index}`}>
            <span className="absolute left-0 top-1.5 size-[15px] rounded-full border-[4px] border-card bg-ink shadow-sm ring-1 ring-verified/25" />
            <time className="text-xs font-semibold tabular-nums text-ink-3">{item.date || "时间待定"}</time>
            <div>
              <h3 className="text-[17px] font-semibold tracking-[-0.02em]">{item.title}</h3>
              <p className="mt-2 text-sm leading-6 text-ink-2">{item.description}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {item.event_ids.map((id) => (
                  <span className="rounded-md bg-paper-2 px-2 py-1 font-mono text-[10px] text-ink-2" title={eventMap.get(id)?.title} key={id}>
                    {id}
                  </span>
                ))}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function CasesView({ cases, sourceMap }: { cases: Fact[]; sourceMap: Map<string, Source> }) {
  if (!cases.length) return <Empty message="尚未找到达到核验门槛的真实人物案例。" />;
  return (
    <div>
      <SectionTitle eyebrow="People" title="真实案例" note={`${cases.length} 个已核验案例`} />
      <div className="mt-8 grid gap-4 md:grid-cols-2">
        {cases.map((fact, index) => (
          <article className="rounded-2xl bg-paper-2 p-5 ring-1 ring-rule" key={fact.id}>
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-3">Case {String(index + 1).padStart(2, "0")}</span>
              <span className="text-xs font-semibold text-verified">可信度 {confidenceLabel(fact.confidence)}</span>
            </div>
            <h3 className="mt-4 text-[17px] font-semibold leading-7 tracking-[-0.015em]">
              {fact.people[0] || "来源中的真实当事人"}
            </h3>
            <p className="mt-3 text-sm leading-6 text-ink-2">{fact.statement}</p>
            <dl className="mt-5 grid grid-cols-[58px_1fr] gap-y-2 border-t border-rule pt-4 text-xs">
              <dt className="text-ink-3">时间</dt>
              <dd className="text-ink-2">{fact.date || "来源未明确"}</dd>
              <dt className="text-ink-3">地点</dt>
              <dd className="text-ink-2">{fact.locations.join("、") || "来源未明确"}</dd>
              <dt className="text-ink-3">来源</dt>
              <dd className="flex flex-wrap gap-x-2 gap-y-1">
                {fact.source_ids.map((id) => {
                  const source = sourceMap.get(id);
                  return source ? (
                    <a className="text-accent hover:underline" href={source.url} target="_blank" rel="noreferrer" key={id}>
                      {source.publisher || source.title}
                    </a>
                  ) : (
                    <span className="font-mono text-ink-3" key={id}>{id}</span>
                  );
                })}
              </dd>
            </dl>
          </article>
        ))}
      </div>
    </div>
  );
}

function DataView({ facts, sourceMap }: { facts: Fact[]; sourceMap: Map<string, Source> }) {
  if (!facts.length) return <Empty message="尚未找到达到核验门槛的关键数据。" />;
  return (
    <div>
      <SectionTitle eyebrow="Verified data" title="关键数据" note={`${facts.length} 条已核验数据`} />
      <div className="mt-8 space-y-3">
        {facts.map((fact) => (
          <article className="grid gap-4 rounded-2xl p-5 ring-1 ring-rule sm:grid-cols-[150px_1fr]" key={fact.id}>
            <div>
              <p className="text-2xl font-semibold tracking-[-0.04em] text-verified">{fact.numbers[0] || "数据"}</p>
              <p className="mt-1 text-xs text-ink-3">{fact.date || "日期见来源"}</p>
            </div>
            <div>
              <p className="text-sm leading-6 text-ink-2">{fact.statement}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {fact.source_ids.map((id) => {
                  const source = sourceMap.get(id);
                  return source ? (
                    <a className="text-xs text-accent hover:underline" href={source.url} target="_blank" rel="noreferrer" key={id}>
                      {source.publisher || source.title}
                    </a>
                  ) : null;
                })}
              </div>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function SourcesView({ sources, facts }: { sources: Source[]; facts: Fact[] }) {
  if (!sources.length) return <Empty message="来源尚未获取。" />;
  const factCounts = new Map<string, number>();
  facts.forEach((fact) => fact.source_ids.forEach((id) => factCounts.set(id, (factCounts.get(id) ?? 0) + 1)));
  return (
    <div>
      <SectionTitle eyebrow="Traceability" title="全部来源" note={`${sources.length} 个独立页面`} />
      <div className="mt-8 divide-y divide-rule rounded-2xl ring-1 ring-rule">
        {sources.map((source) => (
          <article className="p-4 sm:p-5" key={source.id}>
            <div className="flex items-start gap-4">
              <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-paper-2 text-[11px] font-bold uppercase text-ink-2">
                {(source.publisher || "WEB").slice(0, 2)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <a className="line-clamp-2 text-sm font-semibold leading-6 hover:text-verified" href={source.url} target="_blank" rel="noreferrer">
                    {source.title || source.url}
                  </a>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${source.fetch_status === "SUCCESS" ? "bg-verified/[0.08] text-verified" : "bg-pending/[0.07] text-pending"}`}>
                    {source.fetch_status === "SUCCESS" ? "正文已保存" : "抓取失败"}
                  </span>
                </div>
                <p className="mt-1 text-xs text-ink-3">
                  {source.publisher || "未知发布者"} · {source.published_at || "日期未知"} · 可信度 {Math.round(source.credibility_score * 100)}
                </p>
                {source.snippet ? <p className="mt-2 line-clamp-2 text-xs leading-5 text-ink-2">{source.snippet}</p> : null}
                <div className="mt-2 flex flex-wrap gap-2 font-mono text-[10px] text-ink-3">
                  <span>{source.id}</span>
                  <span>支持 {factCounts.get(source.id) ?? 0} 条事实</span>
                  {source.crawler ? <span>{source.crawler}</span> : null}
                </div>
              </div>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function ScriptView({
  topicId,
  payload,
  busy,
  copied,
  onCopy,
  onRewrite,
}: {
  topicId: string;
  payload: ScriptPayload | null;
  busy: boolean;
  copied: boolean;
  onCopy: () => void;
  onRewrite: (duration: 60 | 90 | 180) => void;
}) {
  if (!payload) return <Empty message="剧本会在素材达到最低标准并通过质量审校后出现。" />;
  return (
    <div>
      <div className="flex flex-col gap-4 border-b border-rule pb-6 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-3">Final script</p>
            {payload.review ? (
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${payload.review.passed ? "bg-verified/[0.08] text-verified" : "bg-pending/[0.07] text-pending"}`}>
                质量 {payload.review.score} 分
              </span>
            ) : null}
          </div>
          <h2 className="mt-2 text-[30px] font-semibold tracking-[-0.045em]">人物纪实电影剧本</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="rounded-xl bg-paper-2 px-3.5 py-2 text-xs font-semibold text-ink-2 hover:bg-rule" onClick={onCopy} type="button">
            {copied ? "已复制" : "复制"}
          </button>
          <a className="rounded-xl bg-paper-2 px-3.5 py-2 text-xs font-semibold text-ink-2 hover:bg-rule" href={scriptDownloadUrl(topicId)}>
            导出 Markdown
          </a>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <span className="mr-1 text-xs text-ink-3">重新生成</span>
        {([60, 90, 180] as const).map((duration) => (
          <button
            className="rounded-full px-3 py-1.5 text-xs font-semibold ring-1 ring-rule hover:bg-paper-2 disabled:opacity-40"
            disabled={busy}
            key={duration}
            onClick={() => onRewrite(duration)}
            type="button"
          >
            {duration === 180 ? "3 分钟" : `${duration} 秒`}
          </button>
        ))}
      </div>

      {payload.review?.issues.length ? (
        <div className="mt-5 rounded-xl bg-pending/[0.07] p-4 text-xs leading-5 text-amber-800">
          {payload.review.issues.join("；")}
        </div>
      ) : null}

      {payload.review ? (
        <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            ["因果", payload.review.causality_score],
            ["节奏", payload.review.rhythm_score],
            ["结尾", payload.review.ending_score],
            ["口播", payload.review.narration_fit_score],
          ].map(([label, value]) => (
            <div className="rounded-xl bg-paper-2 px-3 py-2.5 text-xs" key={String(label)}>
              <span className="text-ink-3">{label}</span>
              <span className="ml-2 font-semibold text-ink">{value ?? "—"}</span>
            </div>
          ))}
        </div>
      ) : null}

      {payload.review?.fallback_used ? (
        <div className="mt-4 rounded-xl bg-amber-50 p-4 text-xs leading-5 text-amber-800">
          <p className="font-semibold">
            当前是确定性保底剧本，不是模型产出，不会被标记为成片就绪。
          </p>
          <p className="mt-1">
            审校分数只衡量这份保底稿本身，不能代表剧本层已经通过。生产步骤会因此跳过全部高成本调用，
            请先重新生成剧本，再生成影视包。
          </p>
          {payload.review.generation_reason ? (
            <p className="mt-1">原因：{payload.review.generation_reason}</p>
          ) : null}
        </div>
      ) : null}

      <article className="script-markdown mx-auto mt-10 max-w-[760px]">
        <ReactMarkdown>{payload.script}</ReactMarkdown>
      </article>
    </div>
  );
}

function SectionTitle({ eyebrow, title, note }: { eyebrow: string; title: string; note: string }) {
  return (
    <div className="flex items-end justify-between gap-4">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-3">{eyebrow}</p>
        <h2 className="mt-2 text-[30px] font-semibold tracking-[-0.045em]">{title}</h2>
      </div>
      <p className="text-xs text-ink-3">{note}</p>
    </div>
  );
}

function Empty({ message }: { message: string }) {
  return (
    <div className="grid min-h-72 place-items-center rounded-2xl border border-dashed border-rule px-6 text-center text-sm text-ink-3">
      {message}
    </div>
  );
}
