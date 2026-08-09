import type { TopicStatus } from "@/lib/types";

const labels: Record<TopicStatus, string> = {
  CREATED: "待开始",
  PLANNING: "规划研究",
  SEARCHING: "搜索资料",
  FETCHING: "获取正文",
  EXTRACTING: "提取事实",
  CLUSTERING: "聚合事件",
  VERIFYING: "核验事实",
  TIMELINE: "构建时间线",
  STORY: "分析故事",
  VALUE: "提炼价值",
  WRITING: "编写剧本",
  REVIEWING: "质量审校",
  DIRECTING: "生成影视包",
  COMPLETED: "已完成",
  FAILED: "需要处理",
};

export function StatusPill({ status }: { status: TopicStatus }) {
  const tone =
    status === "COMPLETED"
      ? "bg-verified/[0.08] text-verified ring-verified/15"
      : status === "FAILED"
        ? "bg-pending/[0.08] text-pending ring-pending/15"
        : status === "CREATED"
          ? "bg-ink/[0.05] text-ink-2 ring-ink/10"
          : "bg-accent/[0.08] text-accent ring-accent/15";
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset ${tone}`}
    >
      <span className="size-1.5 rounded-full bg-current opacity-75" />
      {labels[status]}
    </span>
  );
}
