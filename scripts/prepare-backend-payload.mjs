/**
 * 把后端依赖预装进内嵌运行时，并把后端源码收进 runtime/backend。
 *
 * 打包时做完这一步，用户机器上就不需要联网装依赖，也不需要 uv 或 Python。
 * 注意：依赖里有二进制轮子（lxml / primp / pydantic-core），
 * 必须在目标平台上执行——Windows 包只能在 Windows 上打。
 */
import { execFileSync } from "node:child_process";
import { cpSync, existsSync, rmSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const runtimeDir = join(root, "runtime", "python");
const isWindows = process.platform === "win32";
const python = isWindows
  ? join(runtimeDir, "python.exe")
  : join(runtimeDir, "bin", "python3");

if (!existsSync(python)) {
  throw new Error("找不到内嵌 Python，请先运行 npm run runtime:python");
}

console.log("安装后端依赖到内嵌运行时");
execFileSync(
  python,
  [
    "-m",
    "pip",
    "install",
    "--no-warn-script-location",
    "--disable-pip-version-check",
    "-r",
    join(root, "backend", "requirements.txt"),
  ],
  { stdio: "inherit" },
);

const payload = join(root, "runtime", "backend");
rmSync(payload, { recursive: true, force: true });

// 只带运行需要的东西：源码与提示词，不带测试、缓存和本地虚拟环境。
const SKIP = new Set([
  ".venv",
  "__pycache__",
  ".pytest_cache",
  ".ruff_cache",
  "tests",
  ".env",
]);
cpSync(join(root, "backend"), payload, {
  recursive: true,
  filter: (source) => !source.split(/[\\/]/).some((part) => SKIP.has(part)),
});

console.log(`后端已收进 ${payload}`);
