"use client";

import { useEffect, useState } from "react";

import { productionPackageDownloadUrl } from "@/lib/api";
import { copyTextToClipboard } from "@/lib/clipboard";
import type {
  CharacterAsset,
  CinematicShot,
  ProductionPackage,
} from "@/lib/types";

type ReferenceChoice = { enabled: boolean; tag: string };
type ShotEdit = { text: string; revision: number };

interface ProductionWorkspaceProps {
  topicId: string;
  payload: ProductionPackage | null;
  scriptReady: boolean;
  busy: boolean;
  isRunning: boolean;
  onGenerate: () => Promise<void>;
  onRegenerateShot: (
    shotId: string,
    currentPrompt: string,
  ) => Promise<ProductionPackage>;
}

const TAG_PATTERN = /^@[A-Za-z0-9_-]+$/;

function timecode(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function descriptiveCharacter(character: CharacterAsset) {
  return `${character.prompt_label}（${character.visual_anchor}；${character.wardrobe_anchor}）`;
}

export function ProductionWorkspace({
  topicId,
  payload,
  scriptReady,
  busy,
  isRunning,
  onGenerate,
  onRegenerateShot,
}: ProductionWorkspaceProps) {
  const [references, setReferences] = useState<Record<string, ReferenceChoice>>({});
  const [shotEdits, setShotEdits] = useState<Record<string, ShotEdit>>({});
  const [activeIndex, setActiveIndex] = useState(0);
  const [copied, setCopied] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!payload) return;
    const storageKey = `hotstory:${topicId}:character-references`;
    let saved: Record<string, ReferenceChoice> = {};
    try {
      saved = JSON.parse(window.localStorage.getItem(storageKey) || "{}") as Record<
        string,
        ReferenceChoice
      >;
    } catch {
      saved = {};
    }
    const next = Object.fromEntries(
      payload.characters.map((character) => [
        character.id,
        {
          enabled: saved[character.id]?.enabled ?? character.default_use_reference,
          tag: saved[character.id]?.tag ?? "",
        },
      ]),
    );
    setReferences(next);
  }, [payload?.generated_at, payload?.topic_id, topicId]);

  useEffect(() => {
    if (!payload) return;
    setShotEdits((current) =>
      Object.fromEntries(
        payload.shots.map((shot) => {
          const existing = current[shot.shot_id];
          return [
            shot.shot_id,
            existing?.revision === shot.revision
              ? existing
              : { text: shot.prompt_body_template, revision: shot.revision },
          ];
        }),
      ),
    );
    setActiveIndex((current) => Math.min(current, Math.max(payload.shots.length - 1, 0)));
  }, [payload]);

  useEffect(() => {
    if (!payload || !Object.keys(references).length) return;
    window.localStorage.setItem(
      `hotstory:${topicId}:character-references`,
      JSON.stringify(references),
    );
  }, [payload, references, topicId]);

  const activeShot = payload?.shots[activeIndex] ?? null;
  const invalidReferenceCount = (payload?.characters ?? []).filter((character) => {
    const choice = references[character.id];
    return choice?.enabled && !TAG_PATTERN.test(choice.tag.trim());
  }).length;

  function updateReference(characterId: string, patch: Partial<ReferenceChoice>) {
    setReferences((current) => ({
      ...current,
      [characterId]: {
        enabled: current[characterId]?.enabled ?? false,
        tag: current[characterId]?.tag ?? "",
        ...patch,
      },
    }));
  }

  function resolvedPrompt(shot: CinematicShot, template: string) {
    let result = template;
    const referenceLines: string[] = [];
    for (const character of payload?.characters ?? []) {
      const choice = references[character.id];
      const validReference = Boolean(choice?.enabled && TAG_PATTERN.test(choice.tag.trim()));
      const replacement = validReference
        ? choice.tag.trim()
        : descriptiveCharacter(character);
      result = result.replaceAll(`[[${character.reference_token}]]`, replacement);
      if (validReference && shot.active_character_ids.includes(character.id)) {
        referenceLines.push(
          `${choice.tag.trim()}：${character.prompt_label}，${character.visual_anchor}；${character.wardrobe_anchor}。`,
        );
      }
    }
    result = result.replace(/\[\[CHAR_\d+\]\]/g, "影视化还原角色");
    if (!referenceLines.length) return result.trim();
    return `有效参考资产\n${referenceLines.join("\n")}\n\n${result.trim()}`;
  }

  async function copyText(key: string, text: string) {
    try {
      await copyTextToClipboard(text);
      setCopied(key);
      setLocalError(null);
      window.setTimeout(() => setCopied((current) => (current === key ? null : current)), 1600);
    } catch (cause) {
      setLocalError(cause instanceof Error ? cause.message : "复制失败");
    }
  }

  async function regenerateActiveShot() {
    if (!activeShot) return;
    setRegenerating(activeShot.shot_id);
    setLocalError(null);
    try {
      await onRegenerateShot(
        activeShot.shot_id,
        shotEdits[activeShot.shot_id]?.text ?? activeShot.prompt_body_template,
      );
    } catch (cause) {
      setLocalError(cause instanceof Error ? cause.message : "当前生成单元重新优化失败");
    } finally {
      setRegenerating(null);
    }
  }

  if (!payload) {
    return (
      <div className="subtle-grid grid min-h-[430px] place-items-center rounded-2xl border border-dashed border-rule px-6 text-center">
        <div className="max-w-md">
          <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-3">
            Cinematic production
          </p>
          <h2 className="mt-3 text-[28px] font-semibold tracking-[-0.04em]">多镜头影视生成包</h2>
          <p className="mt-3 text-sm leading-6 text-ink-2">
            每 10 秒只生成一次，每次内部自动编排 1–3 个电影微镜头，并保持人物、动作和声音连续。
          </p>
          <button
            className="mt-6 rounded-xl bg-ink px-5 py-3 text-sm font-semibold text-paper disabled:opacity-40"
            disabled={!scriptReady || busy || isRunning}
            onClick={() => void onGenerate()}
            type="button"
          >
            {isRunning ? "正在生成…" : "生成影视包"}
          </button>
          {!scriptReady ? <p className="mt-3 text-xs text-pending">请先生成并通过审校的剧本。</p> : null}
        </div>
      </div>
    );
  }

  const activeTemplate = activeShot
    ? shotEdits[activeShot.shot_id]?.text ?? activeShot.prompt_body_template
    : "";
  const generationUnitCount = payload.generation_unit_count || payload.shots.length;
  const internalShotCount =
    payload.internal_shot_count ||
    payload.shots.reduce((total, shot) => total + Math.max(shot.internal_shots.length, 1), 0);

  return (
    <div>
      <div className="flex flex-col gap-4 border-b border-rule pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-3">
            Cinematic production
          </p>
          <h2 className="mt-2 text-[30px] font-semibold tracking-[-0.045em]">多镜头生成工作台</h2>
          <p className="mt-2 text-xs text-ink-2">
            {generationUnitCount} 次生成 · {internalShotCount} 个内部镜头 · 每次 ≤ {payload.generation_unit_duration_seconds} 秒 · 总时长 {payload.duration_seconds} 秒
          </p>
          <span className={`mt-3 inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold ${payload.ready_for_generation ? "bg-verified/[0.08] text-verified" : "bg-pending/[0.08] text-pending"}`}>
            {payload.ready_for_generation ? `成片就绪 · ${payload.readiness.score}` : `未通过成片就绪门 · ${payload.readiness.score}`}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          <a
            className="rounded-xl bg-paper-2 px-3.5 py-2 text-xs font-semibold text-ink-2 hover:bg-rule"
            href={productionPackageDownloadUrl(topicId)}
          >
            导出 JSON
          </a>
          <button
            className="rounded-xl bg-ink px-3.5 py-2 text-xs font-semibold text-paper disabled:opacity-40"
            disabled={busy || isRunning}
            onClick={() => void onGenerate()}
            type="button"
          >
            {isRunning ? "生成中…" : "重新生成全部"}
          </button>
        </div>
      </div>

      <section className="mt-7">
        <div className="grid gap-3 md:grid-cols-3">
          {payload.skills.map((stage) => (
            <div className="rounded-2xl bg-ink/[0.025] p-5 ring-1 ring-rule" key={stage.skill}>
              <div className="flex items-center gap-3">
                <span className="grid size-9 place-items-center rounded-xl bg-ink text-xs font-bold text-paper">
                  {String(stage.order).padStart(2, "0")}
                </span>
                <p className="text-sm font-semibold">{stage.skill}</p>
              </div>
              <p className="mt-3 text-xs leading-5 text-ink-2">{stage.purpose}</p>
              <p className="mt-2 text-[10px] font-semibold text-verified">
                完整 SKILL 原文 · 无损
              </p>
            </div>
          ))}
        </div>
        <div className="mt-3 rounded-xl bg-verified/[0.07] px-4 py-3 text-xs leading-5 text-verified">
          三份 SKILL.md 均按原文逐字加载；每张生成卡只需提交平台一次，卡内 1–3 个内部镜头由同一次 Seedance 生成完成。角色参考图只有在你填入真实 @标签后才会写入。
          {payload.llm_profile ? ` 当前生成档位：${payload.llm_profile}。` : ""}
        </div>
        {!isRunning && !payload.ready_for_generation ? (
          <div className="mt-3 rounded-xl bg-pending/[0.07] px-4 py-3 text-xs leading-5 text-pending">
            <p className="font-semibold">当前结果只供诊断，复制成片提示词已锁定</p>
            <p className="mt-1">{payload.readiness.blockers.join("；")}</p>
          </div>
        ) : null}
        {isRunning ? (
          <div className="mt-3 rounded-xl bg-verified/[0.07] px-4 py-3 text-xs leading-5 text-verified">
            <p className="font-semibold">正在并行生成新版本</p>
            <p className="mt-1">
              当前页面暂时保留上一次结果；新版本完成后会自动替换，旧的 401 提示不代表本次仍在失败。
            </p>
          </div>
        ) : payload.generation_mode !== "ai_optimized" ? (
          <div className="mt-3 rounded-xl bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-800">
            <p className="font-semibold">
              {payload.generation_mode === "fallback" ? "当前为安全模板模式" : "当前为混合优化模式"}
            </p>
            <p className="mt-1">
              部分模型调用失败，生成单元仍可查看；修复 LLM 配置后点击“重新生成全部”即可获得完整 AI 优化版本。
            </p>
            <details className="mt-2">
              <summary className="cursor-pointer font-semibold">查看原因</summary>
              <ul className="mt-2 space-y-1">
                {payload.warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}
              </ul>
            </details>
          </div>
        ) : null}
      </section>

      <section className="mt-8 grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-2xl bg-paper-2 p-5 ring-1 ring-rule">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-3">Low-cost animatic</p>
              <h3 className="mt-2 text-lg font-semibold">节奏样片检查</h3>
            </div>
            <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold ${payload.animatic.passed ? "bg-verified/[0.08] text-verified" : "bg-pending/[0.08] text-pending"}`}>
              {payload.animatic.score} 分
            </span>
          </div>
          <p className="mt-3 text-xs leading-5 text-ink-2">
            {payload.animatic.generation_unit_count || generationUnitCount} 次生成 · {payload.animatic.internal_shot_count || internalShotCount} 个内部镜头 · 平均 {payload.animatic.average_internal_shot_duration_seconds || payload.animatic.average_shot_duration_seconds} 秒
          </p>
          <div className="mt-4 flex h-16 items-end gap-1 rounded-xl bg-card p-2 ring-1 ring-rule">
            {payload.shots.map((shot) => (
              <button
                aria-label={`${shot.title}，一次生成包含 ${Math.max(shot.internal_shots.length, 1)} 个内部镜头`}
                className="flex h-full min-w-4 items-end gap-px rounded-sm bg-ink/[0.04] p-0.5 transition hover:bg-ink/[0.08]"
                key={`rhythm-${shot.shot_id}`}
                onClick={() => setActiveIndex(payload.shots.findIndex((item) => item.shot_id === shot.shot_id))}
                style={{ flexGrow: shot.duration_seconds }}
                title={`${shot.narrative_function} · 一次生成 ${shot.duration_seconds}s · ${Math.max(shot.internal_shots.length, 1)} 个内部镜头`}
                type="button"
              >
                {(shot.internal_shots.length
                  ? shot.internal_shots
                  : [{
                      internal_shot_id: `${shot.shot_id}_legacy`,
                      start_offset_seconds: 0,
                      end_offset_seconds: shot.duration_seconds,
                      intensity: shot.intensity,
                    }]
                ).map((internal) => (
                  <span
                    className="min-w-px rounded-[2px] bg-verified/75"
                    key={internal.internal_shot_id}
                    style={{
                      flexGrow: internal.end_offset_seconds - internal.start_offset_seconds,
                      height: `${Math.max(14, internal.intensity)}%`,
                    }}
                  />
                ))}
              </button>
            ))}
          </div>
          {payload.animatic.issues.length ? <p className="mt-3 text-xs leading-5 text-pending">{payload.animatic.issues.join("；")}</p> : null}
        </div>

        <div className="rounded-2xl bg-ink p-5 text-paper">
          <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-3">Sound arc</p>
          <h3 className="mt-2 text-lg font-semibold">全片声音曲线</h3>
          <p className="mt-3 text-xs leading-5 text-ink-3">{payload.audio_plan.score_arc}</p>
          <p className="mt-3 text-xs leading-5 text-ink-3">{payload.audio_plan.music_rule}</p>
          <div className="mt-4 space-y-2">
            {payload.audio_plan.cues.map((cue, index) => (
              <div className="rounded-lg bg-white/[0.06] px-3 py-2 text-[11px] leading-4 text-ink-3" key={`${cue.layer}-${cue.start_second}-${index}`}>
                <span className="font-semibold text-paper">{timecode(cue.start_second)}–{timecode(cue.end_second)} · {cue.layer}</span>
                <span className="ml-2">{cue.description}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mt-10">
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-3">Character assets</p>
            <h3 className="mt-2 text-[24px] font-semibold tracking-[-0.035em]">人物参考资产</h3>
          </div>
          <span className="text-xs text-ink-3">{payload.characters.length} 个角色</span>
        </div>

        {payload.characters.length ? (
          <div className="mt-5 grid gap-4 xl:grid-cols-2">
            {payload.characters.map((character) => {
              const choice = references[character.id] ?? {
                enabled: character.default_use_reference,
                tag: "",
              };
              const validTag = TAG_PATTERN.test(choice.tag.trim());
              return (
                <article className="rounded-2xl p-5 ring-1 ring-rule" key={character.id}>
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h4 className="text-[17px] font-semibold">{character.prompt_label}</h4>
                        <span className="rounded-full bg-paper-2 px-2 py-0.5 text-[10px] font-semibold text-ink-2">
                          {character.role === "lead" ? "主角" : "配角"}
                        </span>
                      </div>
                      <p className="mt-1 text-xs leading-5 text-ink-2">{character.story_function}</p>
                    </div>
                    <button
                      className="shrink-0 rounded-lg bg-paper-2 px-3 py-2 text-xs font-semibold hover:bg-rule"
                      onClick={() => void copyText(`character:${character.id}`, character.image_prompt)}
                      type="button"
                    >
                      {copied === `character:${character.id}` ? "已复制" : "复制生图提示词"}
                    </button>
                  </div>

                  <div className="mt-4 rounded-xl bg-ink/[0.025] p-4 text-xs leading-5 text-ink-2">
                    <p>{character.image_prompt}</p>
                    <p className="mt-3 border-t border-rule pt-3 text-ink-3">
                      {character.image_settings.model} · {character.image_settings.aspect_ratio} · {character.image_settings.quality} · {character.image_settings.consistency}
                    </p>
                  </div>

                  <div className="mt-4 grid gap-3 sm:grid-cols-[auto_minmax(0,1fr)] sm:items-center">
                    <label className="flex items-center gap-2 text-xs font-semibold text-ink-2">
                      <input
                        checked={choice.enabled}
                        className="size-4 accent-ink"
                        onChange={(event) => updateReference(character.id, { enabled: event.target.checked })}
                        type="checkbox"
                      />
                      生成单元使用参考图
                    </label>
                    <input
                      className={`rounded-xl border bg-card px-3 py-2 text-xs outline-none focus:ring-2 ${
                        choice.enabled && choice.tag && !validTag
                          ? "border-red-300 focus:ring-red-100"
                          : "border-rule focus:ring-verified/20"
                      }`}
                      disabled={!choice.enabled}
                      onChange={(event) => updateReference(character.id, { tag: event.target.value })}
                      placeholder="填入平台里的真实标签，例如 @hero01"
                      value={choice.tag}
                    />
                  </div>
                  {choice.enabled && !validTag ? (
                    <p className="mt-2 text-[11px] text-pending">未填写有效 @标签时，复制的生成单元会自动改用完整文字角色描述。</p>
                  ) : null}

                  <details className="mt-4 border-t border-rule pt-4">
                    <summary className="cursor-pointer text-xs font-semibold text-ink-2">查看表演主档案与声线</summary>
                    <p className="mt-3 text-xs leading-6 text-ink-2">{character.acting_profile}</p>
                    {character.voice_prompt ? <p className="mt-2 text-xs leading-5 text-ink-2">声线：{character.voice_prompt}</p> : null}
                    <p className="mt-3 text-[11px] text-ink-3">{character.disclosure}</p>
                  </details>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="mt-5 rounded-xl border border-dashed border-rule p-6 text-center text-sm text-ink-3">
            本剧本没有需要持续出镜的核心人物，将直接使用资料、环境与物件镜头。
          </div>
        )}
      </section>

      <section className="mt-12 border-t border-rule pt-9">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-3">Generation unit director</p>
            <h3 className="mt-2 text-[24px] font-semibold tracking-[-0.035em]">10 秒生成单元提示词</h3>
          </div>
          <button
            className="rounded-xl bg-paper-2 px-3.5 py-2 text-xs font-semibold text-ink-2 hover:bg-rule"
            disabled={!payload.ready_for_generation}
            onClick={() =>
              void copyText(
                "all-shots",
                payload.shots
                  .map((shot) => {
                    const template = shotEdits[shot.shot_id]?.text ?? shot.prompt_body_template;
                    return `${shot.title}（一次生成 ${shot.duration_seconds} 秒，内部 ${Math.max(shot.internal_shots.length, 1)} 镜头）\n${resolvedPrompt(shot, template)}`;
                  })
                  .join("\n\n==========\n\n"),
              )
            }
            type="button"
          >
            {payload.ready_for_generation ? (copied === "all-shots" ? "已复制全部" : "复制全部生成单元") : "未就绪，禁止复制"}
          </button>
        </div>

        {invalidReferenceCount ? (
          <div className="mt-4 rounded-xl bg-amber-50 px-4 py-3 text-xs text-amber-800">
            {invalidReferenceCount} 个已启用角色还没有有效 @标签；这些角色当前会使用文字锚点，不影响直接复制生成。
          </div>
        ) : null}
        {localError ? <div className="mt-4 rounded-xl bg-pending/[0.07] px-4 py-3 text-xs text-pending">{localError}</div> : null}

        <div className="mt-5 flex gap-2 overflow-x-auto pb-2">
          {payload.shots.map((shot, index) => (
            <button
              className={`min-w-[138px] rounded-xl p-3 text-left ring-1 transition ${
                index === activeIndex
                  ? "bg-ink text-paper ring-ink"
                  : "bg-card text-ink-2 ring-rule hover:bg-paper-2"
              }`}
              key={shot.shot_id}
              onClick={() => setActiveIndex(index)}
              type="button"
            >
              <span className="text-[10px] font-semibold text-ink-3">
                第 {index + 1} 次生成 · {shot.duration_seconds}s · 内部 {Math.max(shot.internal_shots.length, 1)} 镜 · v{shot.revision}
              </span>
              <span className="mt-1 block truncate text-xs font-semibold">{shot.title}</span>
            </button>
          ))}
        </div>

        {activeShot ? (
          <article className="mt-4 overflow-hidden rounded-2xl ring-1 ring-rule">
            <div className="flex flex-col gap-4 border-b border-rule bg-ink/[0.02] p-5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-xl bg-verified px-2 py-1 text-[10px] font-bold text-paper">
                    {String(activeIndex + 1).padStart(2, "0")}
                  </span>
                  <h4 className="text-[17px] font-semibold">{activeShot.title}</h4>
                  <span className="rounded-full bg-verified/[0.08] px-2 py-0.5 text-[10px] font-semibold text-verified">
                    一次生成 {activeShot.duration_seconds} 秒 · 内部 {Math.max(activeShot.internal_shots.length, 1)} 镜头
                  </span>
                  <span className="text-[10px] text-ink-3">版本 {activeShot.revision}</span>
                  <span className="rounded-full bg-paper-2 px-2 py-0.5 text-[10px] font-semibold text-ink-2">
                    {activeShot.sequence_id} · {activeShot.narrative_function} · 强度 {activeShot.intensity}
                  </span>
                </div>
                <p className="mt-2 text-xs text-ink-2">
                  {timecode(activeShot.start_second)}–{timecode(activeShot.end_second)} · {activeShot.visual_brief}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  className="rounded-lg bg-card px-3 py-2 text-xs font-semibold ring-1 ring-rule disabled:opacity-35"
                  disabled={activeIndex === 0}
                  onClick={() => setActiveIndex((index) => Math.max(index - 1, 0))}
                  type="button"
                >
                  上一生成单元
                </button>
                <button
                  className="rounded-lg bg-card px-3 py-2 text-xs font-semibold ring-1 ring-rule disabled:opacity-35"
                  disabled={activeIndex === payload.shots.length - 1}
                  onClick={() => setActiveIndex((index) => Math.min(index + 1, payload.shots.length - 1))}
                  type="button"
                >
                  下一生成单元
                </button>
              </div>
            </div>

            <div className="p-5">
              {activeShot.narration || activeShot.dialogue ? (
                <div className="mb-4 grid gap-3 sm:grid-cols-2">
                  {activeShot.narration ? (
                    <div className="rounded-xl bg-paper-2 p-3 text-xs leading-5 text-ink-2">
                      <span className="font-semibold text-ink">逐字旁白</span><br />{activeShot.narration}
                    </div>
                  ) : null}
                  {activeShot.dialogue ? (
                    <div className="rounded-xl bg-paper-2 p-3 text-xs leading-5 text-ink-2">
                      <span className="font-semibold text-ink">逐字对白</span><br />{activeShot.dialogue}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {activeShot.internal_shots.length ? (
                <div className="mb-4 rounded-xl bg-ink/[0.025] p-4 ring-1 ring-rule">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-ink">内部镜头时间轴</span>
                    <span className="rounded-full bg-verified/[0.08] px-2 py-0.5 text-[10px] font-semibold text-verified">
                      {activeShot.format_mode === "single_take" ? "单一长镜头" : "受控多镜头"} · 本卡只生成一次
                    </span>
                  </div>
                  <div className="mt-3 grid gap-2 lg:grid-cols-3">
                    {activeShot.internal_shots.map((internal, index) => (
                      <div className="rounded-lg bg-card p-3 text-[11px] leading-5 text-ink-2 ring-1 ring-rule" key={internal.internal_shot_id}>
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-semibold text-ink">
                            {String.fromCharCode(65 + index)} · {internal.start_offset_seconds}–{internal.end_offset_seconds}s
                          </span>
                          <span className="text-[10px] font-semibold text-verified">
                            {internal.shot_size} · {internal.fov_degrees}°
                          </span>
                        </div>
                        {index ? <p className="mt-1 text-[10px] font-semibold text-pending">{internal.cut_in} · {internal.cut_motivation}</p> : null}
                        <p className="mt-2">{internal.visual_action}</p>
                        <p className="mt-2 text-ink-3">摄影机：{internal.camera}</p>
                        <p className="mt-2 border-t border-rule pt-2 text-ink-3">
                          {internal.entry_state} → {internal.exit_state}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="mb-4 grid gap-3 lg:grid-cols-2">
                <div className="rounded-xl bg-paper-2 p-3 text-xs leading-5 text-ink-2">
                  <span className="font-semibold text-ink">表演压力</span><br />
                  目标：{activeShot.objective}<br />阻碍：{activeShot.obstacle}<br />代价：{activeShot.stakes}<br />策略：{activeShot.tactic}
                </div>
                <div className="rounded-xl bg-paper-2 p-3 text-xs leading-5 text-ink-2">
                  <span className="font-semibold text-ink">连续性账本</span><br />
                  入口：{activeShot.entry_state}<br />出口：{activeShot.exit_state}<br />切点：{activeShot.cut_motivation}<br />声音桥：{activeShot.audio_bridge}
                </div>
              </div>

              <label className="text-xs font-semibold text-ink-2" htmlFor={`prompt-${activeShot.shot_id}`}>
                可编辑提示词模板
              </label>
              <textarea
                className="mt-2 min-h-[420px] w-full resize-y rounded-xl border border-rule bg-paper-2 p-4 font-mono text-xs leading-6 text-ink-2 outline-none focus:border-verified/40 focus:bg-card focus:ring-2 focus:ring-verified/20"
                id={`prompt-${activeShot.shot_id}`}
                onChange={(event) =>
                  setShotEdits((current) => ({
                    ...current,
                    [activeShot.shot_id]: {
                      text: event.target.value,
                      revision: activeShot.revision,
                    },
                  }))
                }
                value={activeTemplate}
              />
              <p className="mt-2 text-[11px] leading-5 text-ink-3">
                复制时会自动把角色占位符替换为你填写的真实 @标签；未启用参考图时改用完整文字角色锚点。
              </p>

              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  className="rounded-xl bg-ink px-4 py-2.5 text-xs font-semibold text-paper"
                  disabled={!payload.ready_for_generation}
                  onClick={() => void copyText(activeShot.shot_id, resolvedPrompt(activeShot, activeTemplate))}
                  type="button"
                >
                  {payload.ready_for_generation ? (copied === activeShot.shot_id ? "已复制，可直接生成一次" : "复制当前生成单元") : "未就绪，禁止复制"}
                </button>
                <button
                  className="rounded-xl bg-ink px-4 py-2.5 text-xs font-semibold text-paper disabled:opacity-40"
                  disabled={Boolean(regenerating) || isRunning}
                  onClick={() => void regenerateActiveShot()}
                  type="button"
                >
                  {regenerating === activeShot.shot_id ? "正在重新优化…" : "重新优化当前生成单元"}
                </button>
                <button
                  className="rounded-xl bg-paper-2 px-4 py-2.5 text-xs font-semibold text-ink-2 hover:bg-rule"
                  onClick={() =>
                    setShotEdits((current) => ({
                      ...current,
                      [activeShot.shot_id]: {
                        text: activeShot.prompt_body_template,
                        revision: activeShot.revision,
                      },
                    }))
                  }
                  type="button"
                >
                  恢复生成版本
                </button>
              </div>

              <div className="mt-5 flex flex-wrap gap-2 border-t border-rule pt-4 font-mono text-[10px] text-ink-3">
                {activeShot.event_ids.map((id) => <span key={id}>{id}</span>)}
                {activeShot.source_ids.map((id) => <span key={id}>{id}</span>)}
              </div>
            </div>
          </article>
        ) : null}
      </section>
    </div>
  );
}
