import type { ReactNode } from "react";

// AI 분석 본문 렌더 — 저장된 원문은 그대로 두고 "표시만" 다듬는다.
//  ① 본문에 섞인 이벤트 UUID(인용 잔재)를 제거(근거는 "주요 이슈"·"근거" 섹션에 이미 구조적으로 있음)
//  ② 문장 단위로 문단을 나눠 가독성 확보
//  ③ 검증 가능한 수치·팩트(%·조/억원·날짜·지수 등)를 형광 하이라이트 — 이 프로젝트 정체성(확인 가능성)

const UUID_RE =
  /\s*[([{【]?\s*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\s*[)\]}】]?/gi;

// 하이라이트 대상: 날짜 · 퍼센트 · 금액(조/억/만원) · 지수선 · 배/개국
const FACT_RE =
  /(\d{4}-\d{2}-\d{2}|\d{1,2}월\s?\d{1,2}일|\d[\d,.]*\s?%(?:포인트|p|대)?|\d[\d,.]*\s?(?:조|억|만)\s?원?|\d[\d,.]*\s?원|\d{3,4}선|\d[\d,.]*\s?(?:배|개국))/g;

function clean(text: string): string {
  return text
    .replace(UUID_RE, "") // UUID 토큰(+감싸는 괄호) 제거
    .replace(/\(\s*\)|\[\s*\]|【\s*】/g, "") // 남은 빈 괄호 정리
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([.,)\]])/g, "$1") // 구두점 앞 공백 정리
    .trim();
}

function splitSentences(text: string): string[] {
  const parts = text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
  return parts.length ? parts : [text];
}

function highlight(sentence: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let i = 0;
  let m: RegExpExecArray | null;
  FACT_RE.lastIndex = 0;
  while ((m = FACT_RE.exec(sentence)) !== null) {
    if (m.index > last) nodes.push(sentence.slice(last, m.index));
    nodes.push(
      <mark
        key={`${keyPrefix}-${i++}`}
        className="rounded bg-amber-200/70 px-1 font-semibold text-slate-900"
      >
        {m[0]}
      </mark>,
    );
    last = m.index + m[0].length;
  }
  if (last < sentence.length) nodes.push(sentence.slice(last));
  return nodes;
}

export function AnswerText({ text }: { text: string }) {
  const sentences = splitSentences(clean(text));
  return (
    <div className="flex flex-col gap-3.5">
      {sentences.map((s, i) => (
        <p key={i} className="text-[15px] leading-8 text-slate-700">
          {highlight(s, `s${i}`)}
        </p>
      ))}
    </div>
  );
}
