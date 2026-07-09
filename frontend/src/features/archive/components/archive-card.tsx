import Link from "next/link";
import { FileText, MessageSquareMore } from "lucide-react";

import { formatDate, formatDateTime } from "@/lib/format";
import { archiveItemHref } from "@/lib/report-links";
import type { ArchiveItem } from "@/types/archive";
import { StatusBadge } from "@/components/ui/status-badge";
import { BoldText } from "@/lib/bold-text";
import { DeleteReportButton } from "./delete-report-button";

function toneToStatusTone(tone?: string | null): "green" | "amber" | "red" | "neutral" | "gray" {
  if (tone === "green") return "green";
  if (tone === "amber") return "amber";
  if (tone === "red") return "red";
  return "neutral";
}

export function ArchiveCard({ item }: { item: ArchiveItem }) {
  const href = archiveItemHref(item);
  const body = (
    <article className="group rounded-[28px] border border-slate-200/80 bg-white p-6 shadow-[0_10px_30px_-20px_rgba(15,23,42,0.35)] transition hover:-translate-y-0.5 hover:shadow-[0_18px_45px_-22px_rgba(79,70,229,0.35)]">
      <div className="flex items-start justify-between gap-4">
        <div className="grid h-16 w-16 place-items-center rounded-3xl bg-indigo-50 text-indigo-600">
          <FileText className="h-7 w-7" />
        </div>
        <div className="flex flex-col items-end gap-2">
          {item.card.badge_label && item.card.badge_value ? (
            <StatusBadge
              label={`${item.card.badge_label} ${item.card.badge_value}`}
              tone={toneToStatusTone(item.card.badge_tone)}
            />
          ) : null}
          {item.agent_type === "technical" ||
          item.agent_type === "news" ||
          item.agent_type === "industry" ? (
            <DeleteReportButton reportId={item.report_id} agentType={item.agent_type} />
          ) : null}
        </div>
      </div>

      <div className="mt-6 space-y-3">
        <h2 className="text-2xl font-bold leading-tight tracking-tight text-slate-950">
          {item.card.title}
        </h2>
        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-500">
          <span className="font-medium text-slate-700">{item.stock.stock_name ?? item.stock.stock_code}</span>
          <span>·</span>
          <span>{item.agent_type}</span>
          {item.stock.market ? (
            <>
              <span>·</span>
              <span>{item.stock.market}</span>
            </>
          ) : null}
        </div>
        {item.card.summary ? (
          <p className="line-clamp-3 min-h-[4.5rem] text-sm leading-7 text-slate-600">
            <BoldText text={item.card.summary} />
          </p>
        ) : (
          <p className="min-h-[4.5rem] text-sm leading-7 text-slate-400">
            저장된 요약이 아직 없습니다.
          </p>
        )}
      </div>

      <div className="mt-6 flex flex-wrap gap-2">
        {item.card.meta_primary ? <StatusBadge label={item.card.meta_primary} tone="blue" /> : null}
        {item.status.data_status ? (
          <StatusBadge
            label={item.status.data_status}
            tone={item.status.data_status === "normal" ? "green" : "amber"}
          />
        ) : null}
      </div>

      <div className="mt-6 flex items-center justify-between border-t border-slate-100 pt-5 text-sm text-slate-400">
        <div className="flex items-center gap-2">
          <MessageSquareMore className="h-4 w-4" />
          <span>{item.card.meta_secondary ?? formatDate(item.meta.as_of)}</span>
        </div>
        <time dateTime={item.meta.created_at ?? undefined}>{formatDateTime(item.meta.created_at)}</time>
      </div>
    </article>
  );

  if (!href) {
    return body;
  }

  return (
    <Link href={href} className="block">
      {body}
    </Link>
  );
}
