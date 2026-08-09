import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  agentRules: false,
  // 静态导出：产物由 FastAPI 直接托管，运行时不再需要 Node。
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
};

export default nextConfig;
