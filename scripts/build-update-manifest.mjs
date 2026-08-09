/**
 * 把 CI 各平台产物汇总成 Tauri updater 要的 latest.json。
 *
 * 格式要求（Tauri v2 静态清单）：version 用 SemVer 不带 v，
 * platforms.<OS-ARCH> 下必须有 url 和 signature，signature 是 .sig 文件的内容本身。
 *
 * 用法：node scripts/build-update-manifest.mjs <产物目录> <输出目录>
 */
import {
  copyFileSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";

const [artifactsDir = "artifacts", outputDir = "dist"] = process.argv.slice(2);
const tag = process.env.RELEASE_TAG || "";
const repository = process.env.REPOSITORY || "";
if (!tag || !repository) {
  throw new Error("需要 RELEASE_TAG 与 REPOSITORY 环境变量");
}
const version = tag.replace(/^v/, "");
const downloadBase = `https://github.com/${repository}/releases/download/${tag}`;

/** Tauri 用的平台标识，和产物所在的 target 目录对应。 */
const PLATFORMS = [
  { key: "darwin-aarch64", target: "aarch64-apple-darwin", suffix: ".app.tar.gz" },
  { key: "darwin-x86_64", target: "x86_64-apple-darwin", suffix: ".app.tar.gz" },
  { key: "windows-x86_64", target: "x86_64-pc-windows-msvc", suffix: "-setup.exe" },
];

function walk(dir) {
  const found = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) found.push(...walk(full));
    else found.push(full);
  }
  return found;
}

const files = walk(artifactsDir);
const platforms = {};
mkdirSync(outputDir, { recursive: true });

for (const { key, target, suffix } of PLATFORMS) {
  // 产物按 hotstory-<target> 上传，先按目录名圈定平台，避免跨平台错配。
  const scoped = files.filter((file) => file.includes(`hotstory-${target}`));
  const signature = scoped.find((file) => file.endsWith(`${suffix}.sig`));
  const archive = scoped.find((file) => file.endsWith(suffix));
  if (!signature || !archive) {
    console.warn(`跳过 ${key}：缺少产物或签名`);
    continue;
  }
  // 两个 macOS 架构的更新包都叫 HotStory.app.tar.gz，
  // 传到同一个 Release 会互相覆盖，所以按平台改名后再发。
  const renamed = `HotStory_${version}_${key}${suffix}`;
  copyFileSync(archive, join(outputDir, renamed));
  platforms[key] = {
    url: `${downloadBase}/${renamed}`,
    signature: readFileSync(signature, "utf8").trim(),
  };
  console.log(`收录 ${key} ← ${archive.split("/").pop()} → ${renamed}`);
}

if (Object.keys(platforms).length === 0) {
  throw new Error("没有任何平台产物，拒绝生成空清单");
}

const manifest = {
  version,
  pub_date: new Date().toISOString(),
  notes: `HotStory ${tag}`,
  platforms,
};
writeFileSync(join(outputDir, "latest.json"), JSON.stringify(manifest, null, 2) + "\n");
console.log(`latest.json 已生成，含 ${Object.keys(platforms).length} 个平台`);
