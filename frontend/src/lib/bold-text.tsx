import { Fragment } from "react";

// AI 문장에서 **...** 패턴만 <strong> 으로 렌더한다. **전체 마크다운 파서가 아니다** — 핵심 판단 조건
// 강조(bold)만 처리하고 나머지는 plain text. 매칭 안 되는 별표는 그대로 두지 않고 안전하게 노출 최소화.
export function BoldText({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  const parts = text.split(/(\*\*[^*\n]+\*\*)/g);
  return (
    <>
      {parts.map((part, i) =>
        /^\*\*[^*\n]+\*\*$/.test(part) ? (
          <strong key={i} className="font-bold text-[#0f172a]">
            {part.slice(2, -2)}
          </strong>
        ) : (
          // 잘린 요약 등에서 짝이 안 맞는 잔여 ** 는 노출하지 않도록 제거.
          <Fragment key={i}>{part.replace(/\*\*/g, "")}</Fragment>
        )
      )}
    </>
  );
}
