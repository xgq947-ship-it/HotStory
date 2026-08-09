/**
 * 桌面外壳能力探测。
 *
 * 同一份界面有两种跑法：Tauri 窗口里（能自动更新）和普通浏览器里（dev.sh）。
 * 所以这里只做特性探测，不硬依赖 @tauri-apps/api——浏览器模式下那些包根本不存在。
 * 外壳开了 withGlobalTauri，API 挂在 window.__TAURI__ 上。
 */

export interface UpdateProgress {
  downloaded: number;
  total: number | null;
}

interface TauriUpdate {
  version: string;
  currentVersion: string;
  body?: string | null;
  downloadAndInstall(
    onEvent?: (event: {
      event: "Started" | "Progress" | "Finished";
      data?: { contentLength?: number; chunkLength?: number };
    }) => void,
  ): Promise<void>;
}

interface TauriGlobal {
  updater?: { check(): Promise<TauriUpdate | null> };
  process?: { relaunch(): Promise<void> };
}

function tauri(): TauriGlobal | null {
  if (typeof window === "undefined") return null;
  return (window as unknown as { __TAURI__?: TauriGlobal }).__TAURI__ ?? null;
}

/** 是否运行在桌面外壳里。浏览器里为 false，更新走跳转 GitHub 的老路径。 */
export function isDesktop(): boolean {
  return Boolean(tauri()?.updater);
}

export async function checkDesktopUpdate(): Promise<TauriUpdate | null> {
  const api = tauri();
  if (!api?.updater) return null;
  return api.updater.check();
}

/** 下载并安装。macOS 会替换 .app，Windows 会跑安装程序并自动退出应用。 */
export async function installDesktopUpdate(
  update: TauriUpdate,
  onProgress: (progress: UpdateProgress) => void,
): Promise<void> {
  let downloaded = 0;
  let total: number | null = null;
  await update.downloadAndInstall((event) => {
    if (event.event === "Started") {
      total = event.data?.contentLength ?? null;
      onProgress({ downloaded: 0, total });
    } else if (event.event === "Progress") {
      downloaded += event.data?.chunkLength ?? 0;
      onProgress({ downloaded, total });
    } else if (event.event === "Finished") {
      onProgress({ downloaded: total ?? downloaded, total });
    }
  });
}

export async function relaunchDesktop(): Promise<void> {
  await tauri()?.process?.relaunch();
}
