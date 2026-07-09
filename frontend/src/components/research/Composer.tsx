"use client";

import { useRef, useState } from "react";
import { ArrowUp, ShieldCheck } from "lucide-react";

/**
 * 질의 입력 컴포저 — 목업 renderResearch 하단 폼 디자인.
 * 입력 수집만 담당하고 실제 호출/상태는 상위(useResearchFlow)가 가진다.
 */
export function Composer({
  onSubmit,
  disabled,
}: {
  onSubmit: (query: string) => void;
  disabled?: boolean;
}) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  const autoGrow = () => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  };

  const handleSubmit = () => {
    const q = value.trim();
    if (!q || disabled) return;
    onSubmit(q);
    setValue("");
    if (ref.current) ref.current.style.height = "auto";
  };

  return (
    <div className="shrink-0 border-t border-slate-200/80 bg-white p-5">
      <div className="max-w-3xl mx-auto">
        <div className="bg-slate-50 border border-slate-200 shadow-card focus-within:border-indigo-400 focus-within:bg-white transition-all duration-200 rounded-2xl p-3 flex flex-col">
          <textarea
            ref={ref}
            rows={2}
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              autoGrow();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit();
              }
            }}
            placeholder="종목에 대해 궁금한 점을 적고 분석 요청을 하세요..."
            className="w-full bg-transparent outline-none resize-none text-[14.5px] px-2 text-slate-800 placeholder-slate-400 leading-relaxed"
          />

          <div className="flex items-center justify-between border-t border-slate-200/60 mt-3 pt-3">
            <span className="text-[11px] text-slate-400 flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" /> 검증 게이트 ON
            </span>

            <button
              onClick={handleSubmit}
              disabled={disabled || value.trim() === ""}
              aria-label="분석 요청"
              className="w-10 h-10 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl flex items-center justify-center shadow-md transition disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <ArrowUp className="w-5 h-5" />
            </button>
          </div>
        </div>
        <p className="text-[10.5px] text-slate-400 text-center mt-2.5">
          veriθ의 AI 리포트는 출처가 매핑된 사실 정보만 제공하며, 최종 투자 결정은 투자자 본인의
          판단하에 이루어져야 합니다.
        </p>
      </div>
    </div>
  );
}
