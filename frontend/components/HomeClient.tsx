"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { PHASE_LABELS, PIPELINE_STEPS } from "@/lib/pipeline";
import type { HealthPayload, Hotspot, Topic } from "@/lib/types";

import { Brand } from "./Brand";
import { SettingsDialog } from "./SettingsDialog";
import { StatusPill } from "./StatusPill";

const platformNames: Record<string, string> = {
  baidu: "百度",
  weibo: "微博",
  zhihu: "知乎",
  toutiao: "今日头条",
  trendradar: "TrendRadar",
};

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function HomeClient() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [hotspots, setHotspots] = useState<Hotspot[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.allSettled([
      api<Hotspot[]>("/hotspots"),
      api<Topic[]>("/topics"),
      api<HealthPayload>("/health"),
    ]).then(([hotspotResult, topicResult, healthResult]) => {
      if (!active) return;
      if (hotspotResult.status === "fulfilled") setHotspots(hotspotResult.value);
      if (topicResult.status === "fulfilled") setTopics(topicResult.value);
      if (healthResult.status === "fulfilled") setHealth(healthResult.value);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  async function startResearch(topicTitle: string, inputMode: "manual" | "hotspot") {
    const normalized = topicTitle.trim();
    if (normalized.length < 2) {
      setError("请输入至少两个字的热点主题。 ");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const topic = await api<Topic>("/topics", {
        method: "POST",
        body: JSON.stringify({ title: normalized, input_mode: inputMode }),
      });
      await api(`/topics/${topic.id}/research`, {
        method: "POST",
        body: JSON.stringify({ duration: 90 }),
      });
      router.push(`/topic?id=${encodeURIComponent(topic.id)}`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "无法连接本地 HotStory 服务。 ");
      setSubmitting(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void startResearch(title, "manual");
  }

  return (
    <div className="min-h-screen">
      <header className="bench-nav sticky top-0 z-30">
        <div className="mx-auto flex h-14 max-w-[1180px] items-center justify-between px-5 sm:px-8">
          <Brand />
          <div className="flex items-center gap-4">
            <span className="hidden items-center gap-2 sm:flex">
              <span
                className={`size-1.5 rounded-full ${health?.llm_ready ? "bg-verified" : "bg-pending"}`}
              />
              <span className="gauge text-ink-2">
                {health ? `${health.llm_provider}/${health.search_provider}` : "OFFLINE"}
              </span>
            </span>
            <button
              className="gauge rounded-2xl border border-rule px-2.5 py-1.5 text-ink-2 transition hover:border-ink hover:text-ink"
              onClick={() => setSettingsOpen(true)}
            >
              设置
            </button>
          </div>
        </div>
      </header>

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />

      <main className="mx-auto max-w-[1180px] px-5 pb-24 sm:px-8">
        {/* 台面：左边是仪器，右边是进来的料。不做居中的营销大标题。 */}
        <section className="grid gap-px border-x border-b border-rule bg-rule lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
          <div className="bg-paper px-6 pb-7 pt-12 sm:px-9 sm:pt-16">
            <p className="label">选题台 / INTAKE</p>
            <h1 className="display mt-4 text-[38px] sm:text-[52px]">
              把热点还原成
              <br />
              一条有证据的故事线
            </h1>
            <p className="mt-5 max-w-[46ch] text-[15px] leading-[1.75] text-ink-2">
              每一句话都挂着来源编号。素材不够就停下，不替你编。
            </p>

            <form className="sheet mt-8 rounded-2xl" onSubmit={submit}>
              <textarea
                className="min-h-[104px] w-full resize-none bg-transparent px-4 py-3.5 text-[16px] leading-[1.7] outline-none placeholder:text-ink-3"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="输入一个值得深入研究的热点……"
                maxLength={500}
                aria-label="热点主题"
              />
              <div className="flex items-center justify-between gap-4 border-t border-rule px-4 py-2.5">
                <span className="gauge text-ink-3">{title.trim().length}/500</span>
                <button
                  className="rounded-xl border border-ink bg-ink px-4 py-2 text-[13px] font-medium text-paper transition hover:bg-ink-2 disabled:border-rule disabled:bg-transparent disabled:text-ink-3"
                  type="submit"
                  disabled={submitting || title.trim().length < 2}
                >
                  {submitting ? "建立档案中…" : "开始深度研究"}
                </button>
              </div>
            </form>

            {error ? (
              <p className="mt-3 border-l-2 border-pending bg-pending/[0.07] px-3 py-2.5 text-[13px] text-ink">
                {error}
              </p>
            ) : null}

            {/* 产品论点：13 步引带。开始前就让人看见会发生什么。 */}
            <div className="mt-11 border-t border-rule pt-5">
              <div className="flex items-baseline justify-between">
                <p className="label">流程</p>
                <span className="gauge text-ink-3">13 步 · 每步可中断续跑</span>
              </div>
              <ol className="mt-4 grid gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-4">
                {Object.entries(PHASE_LABELS).map(([phase, label], phaseIndex) => {
                  const steps = PIPELINE_STEPS.filter((step) => step.phase === phase);
                  return (
                    <li key={phase}>
                      <div className="flex items-baseline gap-2 border-b border-ink pb-1.5">
                        <span className="gauge text-ink-3">
                          {String(phaseIndex + 1).padStart(2, "0")}
                        </span>
                        <span className="text-[13px] font-semibold tracking-[-0.01em]">{label}</span>
                        <span className="gauge ml-auto text-ink-3">{steps.length}</span>
                      </div>
                      <ul className="mt-2 space-y-1">
                        {steps.map((step) => (
                          <li className="text-[12.5px] leading-[1.5] text-ink-2" key={step.id}>
                            {step.label}
                          </li>
                        ))}
                      </ul>
                    </li>
                  );
                })}
              </ol>
            </div>
          </div>

          {/* 热榜按线报排：名次用等宽，标题可点。 */}
          <aside className="bg-paper-2 px-6 pb-7 pt-12 sm:px-8 sm:pt-16">
            <div className="flex items-baseline justify-between">
              <p className="label">今日热榜 / WIRE</p>
              <span className="gauge text-ink-3">已滤政治</span>
            </div>

            {loading ? (
              <div className="mt-5 space-y-3">
                {[0, 1, 2, 3, 4, 5].map((item) => (
                  <div className="h-9 animate-pulse bg-rule/50" key={item} />
                ))}
              </div>
            ) : hotspots.length ? (
              <ul className="mt-4">
                {hotspots.slice(0, 8).map((hotspot, index) => (
                  <li
                    className="border-t border-rule first:border-t-0"
                    key={`${hotspot.platform}-${hotspot.rank}-${hotspot.title}`}
                  >
                    <button
                      className="group flex w-full items-start gap-3 py-2.5 text-left disabled:opacity-40"
                      type="button"
                      disabled={submitting}
                      onClick={() => void startResearch(hotspot.title, "hotspot")}
                    >
                      <span className="gauge mt-[3px] w-4 shrink-0 text-ink-3">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13.5px] leading-[1.5] text-ink group-hover:underline">
                          {hotspot.title}
                        </span>
                        <span className="gauge mt-1 block text-ink-3">
                          {platformNames[hotspot.platform] ?? hotspot.platform} · 潜力{" "}
                          {hotspot.story_score}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-5 text-[13px] leading-relaxed text-ink-2">
                热榜暂时没有返回内容。直接在左边输入热点即可开始。
              </p>
            )}
          </aside>
        </section>

        {/* 档案：像索引一样排，编号和时间用等宽。 */}
        <section className="mt-16">
          <div className="flex items-baseline justify-between border-b border-ink pb-2.5">
            <h2 className="text-[15px] font-semibold tracking-[-0.02em]">研究档案</h2>
            <span className="gauge text-ink-3">{topics.length} 份</span>
          </div>

          {topics.length ? (
            <ul>
              {topics.slice(0, 10).map((topic) => (
                <li className="border-b border-rule" key={topic.id}>
                  <Link
                    className="group flex items-center gap-4 py-3 transition hover:bg-card"
                    href={`/topic?id=${encodeURIComponent(topic.id)}`}
                  >
                    <span className="gauge hidden w-24 shrink-0 text-ink-3 sm:block">
                      {formatDate(topic.created_at)}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[14px] group-hover:underline">
                      {topic.title}
                    </span>
                    <StatusPill status={topic.status} />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="border-b border-rule py-10 text-center text-[13px] text-ink-3">
              还没有研究档案
            </p>
          )}
        </section>

        <footer className="mt-14 flex flex-col gap-1.5 text-[11px] text-ink-3 sm:flex-row sm:justify-between">
          <span className="gauge">数据保存在本机</span>
          <span className="gauge">真实性 &gt; 戏剧性 · 来源 &gt; AI 推断</span>
        </footer>
      </main>
    </div>
  );
}
