import Link from "next/link";

export function Brand() {
  return (
    <Link className="group flex items-center gap-2.5" href="/" aria-label="返回 HotStory 首页">
      <span className="grid size-8 place-items-center rounded-[10px] bg-ink text-[11px] font-bold tracking-[-0.04em] text-white shadow-sm">
        HS
      </span>
      <span className="text-[17px] font-semibold tracking-[-0.025em]">HotStory</span>
    </Link>
  );
}
