"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type {
  CodexStatus,
  SettingFieldState,
  SettingsPayload,
  UpdateCheckPayload,
} from "@/lib/types";

type Page = "advanced" | "about" | "whatsnew" | "support";

const PAGES: { id: Page; label: string; icon: string }[] = [
  { id: "advanced", label: "高级", icon: "M10.3 3.2a1 1 0 0 1 1.4 0l1 1a1 1 0 0 1 0 1.4l-6.6 6.6-2.4 1 1-2.4Z" },
  { id: "about", label: "关于", icon: "" },
  { id: "whatsnew", label: "新功能", icon: "" },
  { id: "support", label: "支持", icon: "" },
];

const AUTO_CHECK_KEY = "hotstory.autoCheckUpdates";
const LAST_CHECK_KEY = "hotstory.lastUpdateCheck";
const REPOSITORY_URL = "https://github.com/xgq947-ship-it/HotStory";
const WECHAT_ID = "Moment_oo7";

function NavIcon({ page, active }: { page: Page; active: boolean }) {
  const tone = active ? "currentColor" : "currentColor";
  const common = { fill: "none", stroke: tone, strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (page === "advanced")
    return (
      <svg viewBox="0 0 24 24" className="size-[18px]" {...common}>
        <path d="M14.7 6.3a4 4 0 0 1-5 5L5 16v3h3l4.7-4.7a4 4 0 0 1 5-5l1.6-1.6-2.9-2.9Z" />
      </svg>
    );
  if (page === "about")
    return (
      <svg viewBox="0 0 24 24" className="size-[18px]" {...common}>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 11v5M12 8h.01" />
      </svg>
    );
  if (page === "whatsnew")
    return (
      <svg viewBox="0 0 24 24" className="size-[18px]" {...common}>
        <path d="m12 3 2 5 5 2-5 2-2 5-2-5-5-2 5-2Z" />
      </svg>
    );
  return (
    <svg viewBox="0 0 24 24" className="size-[18px]" {...common}>
      <path d="M12 20s-7-4.4-7-9a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 4.6-7 9-7 9Z" />
    </svg>
  );
}

function AppIcon({ className = "" }: { className?: string }) {
  return (
    <span
      className={`grid place-items-center rounded-[22px] bg-ink font-bold tracking-[-0.05em] text-paper shadow-sm ${className}`}
    >
      HS
    </span>
  );
}

export function SettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [page, setPage] = useState<Page>("advanced");
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string | number | boolean>>({});
  const [cleared, setCleared] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [codex, setCodex] = useState<CodexStatus | null>(null);
  const [codexBusy, setCodexBusy] = useState(false);
  const [update, setUpdate] = useState<UpdateCheckPayload | null>(null);
  const [updateBusy, setUpdateBusy] = useState(false);
  const [autoCheck, setAutoCheck] = useState(true);
  const [lastCheck, setLastCheck] = useState<string>("");
  const autoCheckedRef = useRef(false);

  const load = useCallback(async () => {
    try {
      setSettings(await api<SettingsPayload>("/settings"));
      setError(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "无法读取设置");
    }
  }, []);

  const checkUpdates = useCallback(async () => {
    setUpdateBusy(true);
    try {
      const payload = await api<UpdateCheckPayload>("/settings/updates", { timeoutMs: 20000 });
      setUpdate(payload);
      const stamp = new Date().toLocaleString("zh-CN");
      setLastCheck(stamp);
      window.localStorage.setItem(LAST_CHECK_KEY, stamp);
    } catch (cause) {
      setUpdate({
        current_version: settings?.version ?? "",
        latest: null,
        update_available: false,
        releases: [],
        error: cause instanceof ApiError ? cause.message : "检查更新失败",
      });
    } finally {
      setUpdateBusy(false);
    }
  }, [settings?.version]);

  useEffect(() => {
    if (!open) return;
    setAutoCheck(window.localStorage.getItem(AUTO_CHECK_KEY) !== "false");
    setLastCheck(window.localStorage.getItem(LAST_CHECK_KEY) ?? "");
    void load();
  }, [open, load]);

  // 打开设置时自动检查一次，和参考实现一致；一次会话只查一次。
  useEffect(() => {
    if (!open || !autoCheck || autoCheckedRef.current) return;
    autoCheckedRef.current = true;
    void checkUpdates();
  }, [open, autoCheck, checkUpdates]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    // 不锁住 body 的话，滚轮会把背后的页面滚走，弹窗看起来像是"飘"了。
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, onClose]);

  const dirty = Object.keys(drafts).length > 0 || cleared.length > 0;

  const grouped = useMemo(() => {
    if (!settings) return [];
    // 当前生效值：草稿优先，其次后端返回值。
    const effective = (name: string) => {
      if (drafts[name] !== undefined) return String(drafts[name]);
      return String(settings.fields.find((item) => item.name === name)?.value ?? "");
    };
    const visible = (item: SettingFieldState) => {
      if (!item.depends_on) return true;
      const [target, expected] = item.depends_on;
      return expected.split("|").includes(effective(target));
    };
    return Object.entries(settings.groups)
      .map(([id, label]) => ({
        id,
        label,
        fields: settings.fields.filter((item) => item.group === id && visible(item)),
      }))
      .filter((group) => group.fields.length > 0);
  }, [settings, drafts]);

  function setDraft(name: string, value: string | number | boolean) {
    setDrafts((current) => ({ ...current, [name]: value }));
    setCleared((current) => current.filter((item) => item !== name));
  }

  function clearField(name: string) {
    setDrafts((current) => {
      const next = { ...current };
      delete next[name];
      return next;
    });
    setCleared((current) => (current.includes(name) ? current : [...current, name]));
  }

  async function save() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const payload = await api<SettingsPayload>("/settings", {
        method: "POST",
        body: JSON.stringify({ values: drafts, clear: cleared }),
        timeoutMs: 30000,
      });
      setSettings(payload);
      setDrafts({});
      setCleared([]);
      setNotice("已保存并立即生效");
      window.setTimeout(() => setNotice(null), 2600);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function detectCodex() {
    setCodexBusy(true);
    try {
      const path = String(drafts.codex_cli_path ?? currentValue("codex_cli_path") ?? "");
      const status = await api<CodexStatus>("/settings/codex/detect", {
        method: "POST",
        body: JSON.stringify({ path }),
        timeoutMs: 20000,
      });
      setCodex(status);
      if (status.available && status.path) setDraft("codex_cli_path", status.path);
    } catch (cause) {
      setCodex({
        available: false,
        path: "",
        version: "",
        error: cause instanceof ApiError ? cause.message : "检测失败",
        searched: [],
      });
    } finally {
      setCodexBusy(false);
    }
  }

  function currentValue(name: string) {
    return settings?.fields.find((item) => item.name === name)?.value ?? "";
  }

  function toggleAutoCheck(next: boolean) {
    setAutoCheck(next);
    window.localStorage.setItem(AUTO_CHECK_KEY, String(next));
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/25 p-4 backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-label="HotStory 设置"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="relative flex h-[min(760px,92vh)] w-full max-w-[1080px] overflow-hidden rounded-[24px] bg-paper shadow-[0_30px_90px_-20px_rgba(9,9,11,0.45)] ring-1 ring-rule">
        <button
          className="absolute right-5 top-5 z-10 grid size-9 place-items-center rounded-full bg-card text-ink-2 shadow-sm ring-1 ring-rule transition hover:text-ink"
          onClick={onClose}
          aria-label="关闭设置"
        >
          <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round">
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>

        <nav className="hidden w-[220px] shrink-0 flex-col gap-1 border-r border-rule bg-card/70 p-4 sm:flex">
          {PAGES.map((item) => (
            <button
              key={item.id}
              onClick={() => setPage(item.id)}
              className={`flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-left text-sm font-medium transition ${
                page === item.id
                  ? "bg-ink text-paper shadow-sm"
                  : "text-ink-2 hover:bg-paper-2"
              }`}
            >
              <NavIcon page={item.id} active={page === item.id} />
              {item.label}
            </button>
          ))}
        </nav>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex-1 overflow-y-auto px-6 py-7 sm:px-10">
            {page === "advanced" ? (
              <AdvancedPage
                groups={grouped}
                drafts={drafts}
                cleared={cleared}
                onChange={setDraft}
                onClear={clearField}
                codex={codex}
                codexBusy={codexBusy}
                onDetectCodex={detectCodex}
                loading={!settings}
              />
            ) : null}

            {page === "about" ? (
              <AboutPage
                version={settings?.version ?? ""}
                autoCheck={autoCheck}
                onToggleAutoCheck={toggleAutoCheck}
                update={update}
                busy={updateBusy}
                onCheck={checkUpdates}
                lastCheck={lastCheck}
                onOpenWhatsNew={() => setPage("whatsnew")}
              />
            ) : null}

            {page === "whatsnew" ? <WhatsNewPage update={update} busy={updateBusy} /> : null}
            {page === "support" ? <SupportPage /> : null}
          </div>

          {page === "advanced" ? (
            <footer className="flex items-center justify-between gap-4 border-t border-rule bg-card/70 px-6 py-4 sm:px-10">
              <p className="min-w-0 truncate text-xs text-ink-2">
                {error ? (
                  <span className="text-pending">{error}</span>
                ) : notice ? (
                  <span className="text-verified">{notice}</span>
                ) : (
                  "手动填写的值保存在本机 data/config/settings.json，优先级高于 .env"
                )}
              </p>
              <div className="flex shrink-0 items-center gap-2">
                <button
                  className="rounded-full px-4 py-2 text-sm font-medium text-ink-2 transition hover:text-ink disabled:opacity-40"
                  onClick={() => {
                    setDrafts({});
                    setCleared([]);
                  }}
                  disabled={!dirty || saving}
                >
                  放弃修改
                </button>
                <button
                  className="rounded-full bg-ink px-5 py-2 text-sm font-semibold text-paper shadow-sm transition hover:bg-ink-2 disabled:opacity-40"
                  onClick={() => void save()}
                  disabled={!dirty || saving}
                >
                  {saving ? "保存中…" : "保存"}
                </button>
              </div>
            </footer>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function AdvancedPage({
  groups,
  drafts,
  cleared,
  onChange,
  onClear,
  codex,
  codexBusy,
  onDetectCodex,
  loading,
}: {
  groups: { id: string; label: string; fields: SettingFieldState[] }[];
  drafts: Record<string, string | number | boolean>;
  cleared: string[];
  onChange: (name: string, value: string | number | boolean) => void;
  onClear: (name: string) => void;
  codex: CodexStatus | null;
  codexBusy: boolean;
  onDetectCodex: () => void;
  loading: boolean;
}) {
  if (loading) return <p className="text-sm text-ink-2">正在读取设置…</p>;
  if (!groups.length) return <p className="text-sm text-ink-2">没有匹配的设置项。</p>;

  return (
    <div className="space-y-8">
      {groups.map((group) => (
        <section key={group.id}>
          <h2 className="mb-3 text-[13px] font-semibold uppercase tracking-[0.12em] text-ink-3">
            {group.label}
          </h2>
          <div className="overflow-hidden rounded-2xl bg-card ring-1 ring-rule">
            {group.fields.map((item, index) => (
              <SettingRow
                key={item.name}
                field={item}
                draft={drafts[item.name]}
                isCleared={cleared.includes(item.name)}
                first={index === 0}
                onChange={onChange}
                onClear={onClear}
              />
            ))}
          </div>
          {group.id === "codex" ? (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <button
                className="inline-flex items-center gap-2 rounded-full bg-paper-2 px-4 py-2 text-sm font-medium text-ink-2 transition hover:bg-rule/60 disabled:opacity-50"
                onClick={onDetectCodex}
                disabled={codexBusy}
              >
                {codexBusy ? "检测中…" : "自动检测 Codex CLI"}
              </button>
              {codex ? (
                <span className={`text-xs ${codex.available ? "text-verified" : "text-pending"}`}>
                  {codex.available
                    ? `已找到 ${codex.version || "codex"} · ${codex.path}`
                    : codex.error}
                </span>
              ) : (
                <span className="text-xs text-ink-3">
                  会依次查找 PATH、~/.local/bin、Homebrew 与 ChatGPT.app 内置的 codex
                </span>
              )}
            </div>
          ) : null}
        </section>
      ))}
    </div>
  );
}

function SettingRow({
  field,
  draft,
  isCleared,
  first,
  onChange,
  onClear,
}: {
  field: SettingFieldState;
  draft: string | number | boolean | undefined;
  isCleared: boolean;
  first: boolean;
  onChange: (name: string, value: string | number | boolean) => void;
  onClear: (name: string) => void;
}) {
  const edited = draft !== undefined || isCleared;
  const disabled = !field.editable;

  return (
    <div
      className={`flex flex-col gap-2 px-4 py-3.5 sm:flex-row sm:items-center sm:gap-5 ${
        first ? "" : "border-t border-rule"
      }`}
    >
      <div className="min-w-0 sm:w-[46%]">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-ink">{field.label}</span>
          {edited ? (
            <span className="rounded-full bg-pending/[0.12] px-1.5 py-0.5 text-[10px] font-medium text-pending">
              未保存
            </span>
          ) : null}
          {field.restart_required ? (
            <span className="rounded-full bg-paper-2 px-1.5 py-0.5 text-[10px] text-ink-2">
              需重启
            </span>
          ) : null}
        </div>
        <p className="mt-0.5 text-xs leading-relaxed text-ink-2">
          {field.help || <code className="text-[11px] text-ink-3">{field.name}</code>}
        </p>
      </div>

      <div className="flex min-w-0 flex-1 items-center justify-end gap-2">
        {field.kind === "boolean" ? (
          <Toggle
            checked={Boolean(draft ?? field.value)}
            disabled={disabled}
            onChange={(next) => onChange(field.name, next)}
          />
        ) : field.kind === "select" ? (
          <select
            className="w-full max-w-[280px] rounded-xl bg-paper-2 px-3 py-2 text-sm outline-none ring-1 ring-transparent transition focus:bg-card focus:ring-ink/40 disabled:opacity-50"
            value={String(draft ?? field.value ?? "")}
            disabled={disabled}
            onChange={(event) => onChange(field.name, event.target.value)}
          >
            {field.options.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        ) : (
          <input
            className="w-full max-w-[280px] rounded-xl bg-paper-2 px-3 py-2 text-sm outline-none ring-1 ring-transparent transition focus:bg-card focus:ring-ink/40 disabled:opacity-50"
            type={field.kind === "number" ? "number" : field.secret ? "password" : "text"}
            inputMode={field.kind === "number" ? "decimal" : undefined}
            placeholder={
              isCleared
                ? "（已清除，保存后恢复默认）"
                : field.secret && field.configured
                  ? String(field.value)
                  : field.placeholder
            }
            value={
              draft !== undefined
                ? String(draft)
                : field.secret || isCleared
                  ? ""
                  : String(field.value ?? "")
            }
            disabled={disabled}
            onChange={(event) =>
              onChange(
                field.name,
                field.kind === "number" && event.target.value !== ""
                  ? Number(event.target.value)
                  : event.target.value,
              )
            }
          />
        )}
        {field.secret && field.configured && !isCleared ? (
          <button
            className="shrink-0 rounded-full px-2 py-1 text-xs text-ink-3 transition hover:text-pending"
            onClick={() => onClear(field.name)}
            title="清除已保存的密钥"
          >
            清除
          </button>
        ) : null}
      </div>
    </div>
  );
}

function Toggle({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-[30px] w-[52px] shrink-0 rounded-full transition disabled:opacity-50 ${
        checked ? "bg-ink" : "bg-rule"
      }`}
    >
      <span
        className={`absolute top-[3px] size-6 rounded-full bg-card shadow transition-all ${
          checked ? "left-[25px]" : "left-[3px]"
        }`}
      />
    </button>
  );
}

function AboutPage({
  version,
  autoCheck,
  onToggleAutoCheck,
  update,
  busy,
  onCheck,
  lastCheck,
  onOpenWhatsNew,
}: {
  version: string;
  autoCheck: boolean;
  onToggleAutoCheck: (next: boolean) => void;
  update: UpdateCheckPayload | null;
  busy: boolean;
  onCheck: () => void;
  lastCheck: string;
  onOpenWhatsNew: () => void;
}) {
  return (
    <div className="space-y-8">
      <section className="rounded-2xl bg-card px-6 py-12 text-center ring-1 ring-rule">
        <AppIcon className="mx-auto size-[104px] text-[30px]" />
        <h1 className="mt-6 text-[34px] font-bold tracking-[-0.04em] text-ink">HotStory</h1>
        <p className="mt-1 text-sm text-ink-2">版本 {version || "—"}</p>
        <p className="mx-auto mt-5 max-w-[420px] text-[15px] leading-relaxed text-ink-2">
          本地运行的热点纪实剧本生成器。
          <br />
          先核验事实，再组织时间线、故事与逐镜头影视提示词。
        </p>
        <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
          <button
            className="rounded-full bg-paper-2 px-5 py-2.5 text-sm font-medium text-ink transition hover:bg-rule/60"
            onClick={onOpenWhatsNew}
          >
            查看新功能
          </button>
          <a
            className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline"
            href={REPOSITORY_URL}
            target="_blank"
            rel="noreferrer"
          >
            在 GitHub 上查看
            <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 4h6v6M20 4l-8 8M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
            </svg>
          </a>
        </div>
        <p className="mt-8 text-xs text-ink-3">© 2026 HotStory</p>
      </section>

      <section>
        <h2 className="mb-3 text-[22px] font-semibold tracking-[-0.03em] text-ink">更新</h2>
        <div className="overflow-hidden rounded-2xl bg-card ring-1 ring-rule">
          <div className="flex items-center justify-between gap-5 px-5 py-4">
            <div>
              <p className="text-sm font-medium text-ink">自动检查更新</p>
              <p className="mt-0.5 text-xs text-ink-2">打开设置时从 GitHub Releases 检查</p>
            </div>
            <Toggle checked={autoCheck} onChange={onToggleAutoCheck} />
          </div>

          <div className="flex items-center gap-3 border-t border-rule px-5 py-4">
            {busy ? (
              <>
                <span className="size-6 animate-spin rounded-full border-2 border-rule border-t-ink" />
                <span className="text-sm text-ink-2">正在检查…</span>
              </>
            ) : update?.error ? (
              <>
                <span className="grid size-6 place-items-center rounded-full bg-pending text-paper">!</span>
                <span className="text-sm text-ink-2">{update.error}</span>
              </>
            ) : update?.update_available && update.latest ? (
              <>
                <span className="grid size-6 place-items-center rounded-full bg-ink text-xs text-paper">↓</span>
                <span className="text-sm text-ink">
                  有新版本 {update.latest.tag_name}
                </span>
                <a
                  className="ml-auto rounded-full bg-ink px-4 py-1.5 text-sm font-medium text-paper"
                  href={update.latest.html_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  前往下载
                </a>
              </>
            ) : (
              <>
                <span className="grid size-6 place-items-center rounded-full bg-verified text-xs text-paper">✓</span>
                <span className="text-sm text-ink">你已是最新版本。</span>
              </>
            )}
          </div>

          <div className="border-t border-rule px-5 py-4">
            <button
              className="inline-flex items-center gap-2 rounded-xl bg-paper-2 px-4 py-2 text-sm font-medium text-ink-2 transition hover:bg-rule/60 disabled:opacity-50"
              onClick={onCheck}
              disabled={busy}
            >
              <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6" />
              </svg>
              立即检查
            </button>
          </div>

          {lastCheck ? (
            <p className="border-t border-rule px-5 py-3.5 text-xs text-ink-3">
              上次检查：{lastCheck}
            </p>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function WhatsNewPage({ update, busy }: { update: UpdateCheckPayload | null; busy: boolean }) {
  if (busy) return <p className="text-sm text-ink-2">正在读取发布记录…</p>;
  if (!update || update.error)
    return (
      <div className="rounded-2xl bg-card p-6 text-sm text-ink-2 ring-1 ring-rule">
        {update?.error || "还没有读取到发布记录。"}
      </div>
    );
  if (!update.releases.length)
    return (
      <div className="rounded-2xl bg-card p-6 ring-1 ring-rule">
        <p className="text-sm text-ink-2">
          仓库还没有发布任何 Release。当前运行版本 {update.current_version}。
        </p>
        <a
          className="mt-3 inline-block text-sm font-medium text-accent hover:underline"
          href={`${REPOSITORY_URL}/commits/main`}
          target="_blank"
          rel="noreferrer"
        >
          查看提交记录
        </a>
      </div>
    );
  return (
    <div className="space-y-4">
      {update.releases.map((release) => (
        <article key={release.tag_name} className="rounded-2xl bg-card p-5 ring-1 ring-rule">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-[17px] font-semibold tracking-[-0.02em]">{release.name}</h3>
            <span className="text-xs text-ink-3">
              {release.published_at ? release.published_at.slice(0, 10) : ""}
            </span>
          </div>
          {release.body ? (
            <pre className="mt-3 whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink-2">
              {release.body}
            </pre>
          ) : null}
          <a
            className="mt-3 inline-block text-sm font-medium text-accent hover:underline"
            href={release.html_url}
            target="_blank"
            rel="noreferrer"
          >
            查看发布页
          </a>
        </article>
      ))}
    </div>
  );
}

function SupportPage() {
  const [copied, setCopied] = useState(false);

  async function copyWechat() {
    try {
      await navigator.clipboard.writeText(WECHAT_ID);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <p className="label">SUPPORT</p>
        <h2 className="mt-1.5 text-[26px] font-semibold tracking-[-0.035em]">支持</h2>
        <p className="mt-1.5 text-sm text-ink-2">遇到问题或有功能建议，可以通过微信联系。</p>
      </div>

      <section className="flex items-center gap-4 rounded-2xl bg-card p-6 ring-1 ring-rule">
        <span className="grid size-14 shrink-0 place-items-center rounded-full bg-pending/[0.1] text-pending">
          <svg viewBox="0 0 24 24" className="size-7" fill="currentColor">
            <path d="M12 20s-7-4.4-7-9a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 4.6-7 9-7 9Z" />
          </svg>
        </span>
        <div className="min-w-0 flex-1">
          <span className="text-xs text-ink-3">微信号</span>
          <strong className="mt-0.5 block text-[19px] font-semibold tracking-[-0.02em]">
            {WECHAT_ID}
          </strong>
          <p className="mt-1 text-xs text-ink-2">添加时请备注“HotStory”。</p>
        </div>
        <button
          className="shrink-0 rounded-xl bg-ink px-4 py-2.5 text-[13px] font-medium text-white transition hover:bg-ink-2"
          onClick={() => void copyWechat()}
        >
          {copied ? "已复制" : "复制微信号"}
        </button>
      </section>

      <section className="rounded-2xl bg-card p-6 ring-1 ring-rule">
        <h3 className="text-[15px] font-semibold tracking-[-0.02em]">自助排查</h3>
        <ul className="mt-2.5 space-y-1.5 text-sm leading-relaxed text-ink-2">
          <li>· 搜索结果少：DuckDuckGo 限流，换成 Tavily / Brave / Serper 并填对应 Key。</li>
          <li>· 提示“已有任务在运行”：本地同时只跑一条管道，等它结束即可。</li>
          <li>· 服务被中断：重新打开主题点继续，已完成步骤不会重复消耗额度。</li>
        </ul>
      </section>
    </div>
  );
}
