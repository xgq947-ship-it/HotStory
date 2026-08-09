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

/** 颜色只表示核验状态，不做装饰：绿=成稿可信，赭=需要人介入，黑=在跑。 */
export function StatusPill({ status }: { status: TopicStatus }) {
  const tone =
    status === "COMPLETED"
      ? "border-verified text-verified"
      : status === "FAILED"
        ? "border-pending text-pending"
        : status === "CREATED"
          ? "border-rule text-ink-3"
          : "border-ink text-ink";
  return (
    <span
      className={`gauge inline-flex shrink-0 items-center gap-1.5 border-l-2 py-0.5 pl-2 ${tone}`}
    >
      {labels[status]}
    </span>
  );
}
