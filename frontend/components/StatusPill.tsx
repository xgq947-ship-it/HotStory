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
  const color =
    status === "COMPLETED"
      ? "bg-emerald-50 text-emerald-700 ring-emerald-600/15"
      : status === "FAILED"
        ? "bg-red-50 text-red-700 ring-red-600/15"
        : status === "CREATED"
          ? "bg-zinc-100 text-zinc-600 ring-zinc-500/10"
          : "bg-blue-50 text-blue-700 ring-blue-600/15";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset ${color}`}>
      <span className="size-1.5 rounded-full bg-current opacity-75" />
      {labels[status]}
    </span>
  );
}
