import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost";
type Size = "sm" | "md";

const VARIANT_CLASS: Record<Variant, string> = {
  primary:
    "bg-indigo-600 hover:bg-indigo-700 text-white shadow-md disabled:opacity-40",
  secondary:
    "border border-slate-200 hover:bg-slate-50 text-slate-700 bg-white disabled:opacity-40",
  ghost:
    "text-slate-500 hover:bg-slate-50 hover:text-slate-800 disabled:opacity-40",
};

const SIZE_CLASS: Record<Size, string> = {
  sm: "px-3 py-1.5 text-[11px]",
  md: "px-3.5 py-2.5 text-xs",
};

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

/** 공통 버튼 — mockup 의 indigo primary / outline secondary 톤. */
export function Button({
  variant = "primary",
  size = "md",
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-xl font-bold transition disabled:cursor-not-allowed",
        VARIANT_CLASS[variant],
        SIZE_CLASS[size],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
