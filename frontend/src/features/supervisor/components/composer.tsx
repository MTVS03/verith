"use client";

import { useRef } from "react";
import { ArrowUp, ShieldCheck } from "lucide-react";

// 목업 verith(3).html 의 하단 composer 를 그대로 옮김:
// 회색 라운드 박스 + textarea(자동 높이) + 하단 "Verification Gate ON" / 전송 버튼.
export function Composer({
  onSubmit,
  disabled = false,
}: {
  onSubmit: (query: string) => void;
  disabled?: boolean;
}) {
  const areaRef = useRef<HTMLTextAreaElement>(null);

  function autoGrow() {
    const el = areaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }

  function submit() {
    const el = areaRef.current;
    const query = el?.value.trim();
    if (!query || disabled) return;
    onSubmit(query);
    if (el) {
      el.value = "";
      el.style.height = "auto";
    }
  }

  return (
    <div className="shrink-0 border-t border-slate-200/80 bg-white p-5">
      <div className="mx-auto max-w-3xl">
        <div className="flex flex-col rounded-2xl border border-slate-200 bg-slate-50 p-3 shadow-[0_1px_3px_rgba(15,23,42,0.05)] transition-all duration-200 focus-within:border-indigo-400 focus-within:bg-white">
          <textarea
            ref={areaRef}
            rows={2}
            placeholder="종목에 대해 궁금한 점을 적고 분석 요청을 하세요..."
            onInput={autoGrow}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            disabled={disabled}
            className="w-full resize-none bg-transparent px-2 text-[14.5px] leading-relaxed text-slate-800 outline-none placeholder:text-slate-400 disabled:opacity-60"
          />
          <div className="mt-3 flex items-center justify-between border-t border-slate-200/60 pt-3">
            <span className="flex items-center gap-1 text-[11px] text-slate-400">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" />
              Verification Gate ON
            </span>
            <button
              type="button"
              onClick={submit}
              disabled={disabled}
              aria-label="분석 요청 전송"
              className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-md transition hover:bg-indigo-700 disabled:opacity-40"
            >
              <ArrowUp className="h-5 w-5" />
            </button>
          </div>
        </div>
        <p className="mt-2.5 text-center text-[10.5px] text-slate-400">
          veriθ의 AI 리포트는 출처가 매핑된 사실 정보만 제공하며, 최종 투자 결정은 투자자 본인의 판단하에
          이루어져야 합니다.
        </p>
      </div>
    </div>
  );
}
