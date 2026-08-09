import Link from "next/link";

/** 标记取自片头引带的一格：打孔 + 画面。 */
export function Brand() {
  return (
    <Link className="group flex items-center gap-2.5" href="/" aria-label="返回 HotStory 首页">
      <span className="flex h-7 w-7 items-center gap-[3px] rounded-[3px] bg-ink px-[3px] py-[3px]">
        <span className="flex h-full w-[4px] flex-col justify-between py-[1px]">
          <span className="block h-[3px] w-full rounded-[1px] bg-paper/60" />
          <span className="block h-[3px] w-full rounded-[1px] bg-paper/60" />
          <span className="block h-[3px] w-full rounded-[1px] bg-paper/60" />
        </span>
        <span className="h-full flex-1 rounded-[1px] bg-verified" />
      </span>
      <span className="text-[16px] font-semibold tracking-[-0.03em]">HotStory</span>
    </Link>
  );
}
