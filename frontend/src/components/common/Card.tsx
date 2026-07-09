import { cn } from "@/lib/cn";

/**
 * 공통 카드 컨테이너 — mockup 의 `bg-white rounded-2xl border shadow-card` 패턴.
 * 색/spacing 은 토큰(shadow-card 등)으로만 다룬다(가이드라인 §9.1).
 */
export function Card({
  className,
  children,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "bg-white rounded-2xl border border-slate-200/80 shadow-card",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}
