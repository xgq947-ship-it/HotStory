/** 管道的 13 个步骤。顺序携带信息：后面的步骤依赖前面的产物。 */
export const PIPELINE_STEPS = [
  { id: "plan", label: "研究计划", phase: "research" },
  { id: "search", label: "多轮搜索", phase: "research" },
  { id: "fetch", label: "获取正文", phase: "research" },
  { id: "extract", label: "提取事实", phase: "verify" },
  { id: "cluster", label: "聚合事件", phase: "verify" },
  { id: "verify", label: "交叉核验", phase: "verify" },
  { id: "timeline", label: "构建时间线", phase: "verify" },
  { id: "story", label: "故事分析", phase: "write" },
  { id: "value", label: "价值方向", phase: "write" },
  { id: "write", label: "编写剧本", phase: "write" },
  { id: "review", label: "质量审校", phase: "write" },
  { id: "production", label: "影视生成包", phase: "film" },
  { id: "export", label: "保存档案", phase: "film" },
] as const;

export const PHASE_LABELS: Record<string, string> = {
  research: "调查",
  verify: "核验",
  write: "成稿",
  film: "成片",
};

export const stepLabels: Record<string, string> = Object.fromEntries(
  PIPELINE_STEPS.map((step) => [step.id, step.label]),
);
