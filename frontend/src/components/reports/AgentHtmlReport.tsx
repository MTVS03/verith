"use client";

import { useRef, useState } from "react";

/**
 * 에이전트가 **완성해서 준 HTML 리포트**를 그대로 표시한다(flow.html / fundamental.report_html).
 * 프론트는 렌더만 한다 — 내용/스타일을 만들지 않는다.
 *
 * 격리를 위해 sandbox iframe(srcDoc)에 넣는다: 에이전트 CSS 가 앱 스타일과 섞이지 않고,
 * 스크립트는 실행하지 않는다(allow-scripts 없음). same-origin 으로 로드해 콘텐츠 높이를 측정한다.
 */
export function AgentHtmlReport({ html }: { html: string }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(640);

  const onLoad = () => {
    try {
      const doc = ref.current?.contentDocument;
      const h = doc?.body?.scrollHeight;
      if (h && h > 0) setHeight(h + 24);
    } catch {
      // cross-origin 등으로 높이를 못 재면 기본 높이 유지
    }
  };

  return (
    <iframe
      ref={ref}
      srcDoc={html}
      onLoad={onLoad}
      sandbox="allow-same-origin"
      title="agent-report"
      className="w-full rounded-2xl border border-slate-200/80 bg-white"
      style={{ height }}
    />
  );
}
