"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { HealthPayload, Hotspot, Topic } from "@/lib/types";

import { Brand } from "./Brand";
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
      router.push(`/topics/${topic.id}`);
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
      <header className="glass-nav sticky top-0 z-30">
        <div className="mx-auto flex h-16 max-w-[1120px] items-center justify-between px-5 sm:px-8">
          <Brand />
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <span className={`size-2 rounded-full ${health?.llm_ready ? "bg-emerald-500" : "bg-amber-500"}`} />
            <span className="hidden sm:inline">
              {health ? `${health.llm_provider} · ${health.search_provider}` : "本地服务"}
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1120px] px-5 pb-24 pt-20 sm:px-8 sm:pt-28">
        <section className="mx-auto max-w-[900px] text-center">
          <div className="mb-5 inline-flex items-center rounded-full bg-white px-3 py-1.5 text-[11px] font-semibold tracking-[0.08em] text-zinc-500 ring-1 ring-zinc-950/5">
            LOCAL RESEARCH STUDIO
          </div>
          <h1 className="text-balance text-[42px] font-bold leading-[1.06] tracking-[-0.055em] text-zinc-950 sm:text-[64px]">
            把热点，还原成一条
            <br className="hidden sm:block" />
            有证据的故事线。
          </h1>
          <p className="mx-auto mt-6 max-w-[650px] text-pretty text-[16px] leading-7 text-zinc-500 sm:text-[18px]">
            多轮研究、事实核验、真实案例与完整时间线，最后生成每个关键表达都能回到来源的纪录片式剧本。
          </p>

          <form className="surface mx-auto mt-10 rounded-[22px] p-2.5 text-left" onSubmit={submit}>
            <textarea
              className="min-h-24 w-full resize-none rounded-2xl bg-transparent px-4 py-3 text-[17px] leading-7 tracking-[-0.01em] text-zinc-900 outline-none placeholder:text-zinc-400 sm:min-h-20"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="输入一个值得深入研究的热点……"
              maxLength={500}
              aria-label="热点主题"
            />
            <div className="flex flex-col gap-3 border-t border-zinc-950/[0.06] px-2 pt-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2 px-2 text-xs text-zinc-400">
                <span className="size-1.5 rounded-full bg-blue-500" />
                事实必须可追溯，素材不足时不会强行生成
              </div>
              <button
                className="rounded-[13px] bg-zinc-950 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
                type="submit"
                disabled={submitting || title.trim().length < 2}
              >
                {submitting ? "正在建立研究档案…" : "开始深度研究"}
              </button>
            </div>
          </form>
          {error ? (
            <p className="mt-3 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-red-600/10">
              {error}
            </p>
          ) : null}
        </section>

        <section className="mt-24">
          <div className="mb-6 flex items-end justify-between gap-6">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-400">Today</p>
              <h2 className="mt-1 text-[28px] font-semibold tracking-[-0.04em]">今天的社会纪实选题</h2>
            </div>
            <span className="text-xs text-zinc-400">已过滤政治新闻，入选事实仍会重新核验</span>
          </div>

          {loading ? (
            <div className="grid gap-3 md:grid-cols-3">
              {[0, 1, 2].map((item) => (
                <div className="h-48 animate-pulse rounded-[18px] bg-white/70 ring-1 ring-zinc-950/5" key={item} />
              ))}
            </div>
          ) : hotspots.length ? (
            <div className="grid gap-3 md:grid-cols-3">
              {hotspots.slice(0, 6).map((hotspot) => (
                <article
                  className="surface group flex min-h-48 flex-col rounded-[18px] p-5 transition hover:-translate-y-0.5 hover:shadow-lg hover:shadow-zinc-950/[0.04]"
                  key={`${hotspot.platform}-${hotspot.rank}-${hotspot.title}`}
                >
                  <div className="flex items-center justify-between text-[11px] font-semibold text-zinc-400">
                    <span>{platformNames[hotspot.platform] ?? hotspot.platform}</span>
                    <span>故事潜力 {hotspot.story_score}</span>
                  </div>
                  <h3 className="mt-5 line-clamp-3 text-[18px] font-semibold leading-7 tracking-[-0.02em]">
                    {hotspot.title}
                  </h3>
                  <button
                    className="mt-auto flex items-center justify-between border-t border-zinc-950/[0.06] pt-4 text-left text-sm font-semibold text-blue-600 disabled:opacity-50"
                    type="button"
                    disabled={submitting}
                    onClick={() => void startResearch(hotspot.title, "hotspot")}
                  >
                    研究这个热点 <span aria-hidden="true">→</span>
                  </button>
                </article>
              ))}
            </div>
          ) : (
            <div className="surface rounded-[18px] px-6 py-10 text-center text-sm text-zinc-500">
              热榜服务暂时没有返回内容，你仍可直接输入热点开始研究。
            </div>
          )}
        </section>

        <section className="mt-24">
          <div className="mb-6">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-400">Archive</p>
            <h2 className="mt-1 text-[28px] font-semibold tracking-[-0.04em]">最近研究</h2>
          </div>
          <div className="surface overflow-hidden rounded-[18px]">
            {topics.length ? (
              topics.slice(0, 8).map((topic, index) => (
                <Link
                  className={`flex items-center gap-4 px-5 py-4 transition hover:bg-zinc-950/[0.025] sm:px-6 ${index ? "border-t border-zinc-950/[0.06]" : ""}`}
                  href={`/topics/${topic.id}`}
                  key={topic.id}
                >
                  <span className="hidden w-20 shrink-0 text-xs tabular-nums text-zinc-400 sm:block">
                    {formatDate(topic.created_at)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm font-medium sm:text-[15px]">{topic.title}</span>
                  <StatusPill status={topic.status} />
                  <span className="text-zinc-300" aria-hidden="true">
                    →
                  </span>
                </Link>
              ))
            ) : (
              <div className="px-6 py-12 text-center text-sm text-zinc-400">还没有研究档案</div>
            )}
          </div>
        </section>

        <footer className="mt-24 flex flex-col gap-2 border-t border-zinc-950/[0.06] pt-6 text-xs text-zinc-400 sm:flex-row sm:justify-between">
          <span>HotStory · 数据保存在本机</span>
          <span>真实性 &gt; 戏剧性 · 来源 &gt; AI 推断</span>
        </footer>
      </main>
    </div>
  );
}
