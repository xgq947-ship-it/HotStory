import { Suspense } from "react";

import { TopicRoute } from "@/components/TopicRoute";

// 静态导出不支持没有 generateStaticParams 的动态路由段，
// 所以主题页改成 /topic?id=xxx，由客户端读取查询参数。
export default function TopicPage() {
  return (
    <Suspense
      fallback={
        <div className="grid min-h-screen place-items-center bg-[#f5f5f7]">
          <div className="mx-auto size-7 animate-spin rounded-full border-2 border-zinc-200 border-t-zinc-900" />
        </div>
      }
    >
      <TopicRoute />
    </Suspense>
  );
}
