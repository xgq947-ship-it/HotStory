"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { ResearchWorkspace } from "./ResearchWorkspace";

export function TopicRoute() {
  const id = useSearchParams().get("id")?.trim() ?? "";
  if (!id) {
    return (
      <div className="grid min-h-screen place-items-center bg-paper px-6 text-center">
        <div>
          <p className="text-sm text-ink-2">缺少主题 ID。</p>
          <Link className="mt-3 inline-block text-sm font-medium text-verified hover:underline" href="/">
            返回首页
          </Link>
        </div>
      </div>
    );
  }
  return <ResearchWorkspace topicId={id} />;
}
