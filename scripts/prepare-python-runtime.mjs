/**
 * 下载 standalone CPython 到 runtime/python，随应用一起分发。
 *
 * 和 Reverse Prompt 的 prepare-node-runtime.mjs 同一套路：打包时把解释器抓下来，
 * 用户机器上就不需要装 Python。发行版来自 python-build-standalone，
 * 也就是 uv python install 底层用的那个。
 *
 * 覆盖目标平台：HOTSTORY_RUNTIME_PLATFORM / HOTSTORY_RUNTIME_ARCH
 */
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { createWriteStream, existsSync } from "node:fs";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Readable } from "node:stream";
import { finished } from "node:stream/promises";

const PYTHON_VERSION = "3.12.13";
const RELEASE_TAG = "20260807";
const BASE_URL = `https://github.com/astral-sh/python-build-standalone/releases/download/${RELEASE_TAG}`;

const platform = process.env.HOTSTORY_RUNTIME_PLATFORM || process.platform;
const architecture = process.env.HOTSTORY_RUNTIME_ARCH || process.arch;

const TARGETS = {
  "darwin-arm64": "aarch64-apple-darwin",
  "darwin-x64": "x86_64-apple-darwin",
  "win32-x64": "x86_64-pc-windows-msvc",
  "win32-arm64": "aarch64-pc-windows-msvc",
};

const key = `${platform}-${architecture}`;
const target = TARGETS[key];
if (!target) {
  throw new Error(
    `不支持的 Python 运行时目标：${key}（支持 ${Object.keys(TARGETS).join(", ")}）`,
  );
}

const archiveName = `cpython-${PYTHON_VERSION}+${RELEASE_TAG}-${target}-install_only.tar.gz`;
const outputDir = join(process.cwd(), "runtime", "python");
const markerFile = join(outputDir, ".runtime-target");
const interpreter = join(
  outputDir,
  platform === "win32" ? "python.exe" : join("bin", "python3"),
);

// 已经是同一个目标就跳过；换平台交叉打包时必须重下。
if (existsSync(interpreter) && existsSync(markerFile)) {
  const current = await readFile(markerFile, "utf8");
  if (current.trim() === `${target}@${PYTHON_VERSION}+${RELEASE_TAG}`) {
    console.log(`Python 运行时已就绪：${target}`);
    process.exit(0);
  }
  console.log("运行时目标已变化，重新下载");
  await rm(outputDir, { recursive: true, force: true });
}

async function download(url, destination) {
  const response = await fetch(url, { redirect: "follow" });
  if (!response.ok) throw new Error(`下载失败 ${response.status}：${url}`);
  await finished(Readable.fromWeb(response.body).pipe(createWriteStream(destination)));
}

async function expectedDigest() {
  // 官方为每个产物发布 .sha256，校验后再解压——这是要分发给别人的东西。
  const response = await fetch(`${BASE_URL}/${archiveName}.sha256`, { redirect: "follow" });
  if (!response.ok) return "";
  return (await response.text()).trim().split(/\s+/)[0] ?? "";
}

const tempDir = join(tmpdir(), `hotstory-python-${process.pid}`);
await mkdir(tempDir, { recursive: true });
const archivePath = join(tempDir, archiveName);

try {
  console.log(`下载 ${archiveName}`);
  await download(`${BASE_URL}/${archiveName}`, archivePath);

  const digest = createHash("sha256").update(await readFile(archivePath)).digest("hex");
  const expected = await expectedDigest();
  if (expected && expected !== digest) {
    throw new Error(`校验失败：期望 ${expected}，实际 ${digest}`);
  }
  console.log(`校验通过 sha256=${digest.slice(0, 16)}…`);

  await mkdir(outputDir, { recursive: true });
  // 压缩包顶层是 python/，剥掉一层直接落到 runtime/python
  execFileSync("tar", ["-xzf", archivePath, "-C", outputDir, "--strip-components", "1"], {
    stdio: "inherit",
  });

  if (!existsSync(interpreter)) {
    throw new Error(`解压后找不到解释器：${interpreter}`);
  }
  await writeFile(markerFile, `${target}@${PYTHON_VERSION}+${RELEASE_TAG}\n`, "utf8");
  console.log(`Python 运行时就绪：${outputDir}`);
} finally {
  await rm(tempDir, { recursive: true, force: true });
}
