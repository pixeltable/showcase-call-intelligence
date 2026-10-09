import {
  SENTIMENT_CHIP_CLASSES,
  SENTIMENT_REGION_COLORS,
  momentPolarity,
  sentimentMoments,
} from "../lib/sentiment";
import type { CallDetail } from "../api/client";
import { qaLabel } from "../lib/verticals";

interface Props {
  call: CallDetail;
}

const BULLET_PREFIX = /^[\s•\-*]+/;
const MARKDOWN_BOLD = /\*\*([^*]+)\*\*/g;
const PREAMBLE = /^(here are|below are|summary:|the following|call summary)/i;

function cleanSummaryLine(line: string): string {
  let text = line.trim();
  if (!text || PREAMBLE.test(text)) return "";
  text = text.replace(BULLET_PREFIX, "");
  text = text.replace(MARKDOWN_BOLD, "$1");
  return text.replace(/\*/g, "").trim();
}

function summaryLines(summary: string | null | undefined): string[] {
  if (!summary) return [];
  return summary
    .split("\n")
    .map(cleanSummaryLine)
    .filter(Boolean);
}

function momentLabel(polarity: ReturnType<typeof momentPolarity>): string {
  if (polarity === "positive") return "Positive";
  if (polarity === "neutral") return "Neutral";
  return "Negative";
}

function emptySummary(status: string): string {
  if (status === "completed") return "No summary: no speech detected.";
  if (status === "failed") return "Not available: processing failed.";
  return "Processing...";
}

export function IntelligenceSidebar({ call }: Props) {
  const actionItems = Array.isArray(call.action_items) ? call.action_items : [];
  const moments = sentimentMoments(call.sentiment ?? null);
  const qa = call.qa_scorecard ?? {};
  const bullets = summaryLines(call.summary);
  const rationale = typeof call.sentiment?.rationale === "string" ? call.sentiment.rationale.trim() : "";

  return (
    <aside className="space-y-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <h2 className="text-lg font-semibold">Intelligence</h2>

      <section>
        <h3 className="text-xs uppercase tracking-wide text-slate-400">Summary</h3>
        {bullets.length > 1 ? (
          <ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-slate-200">
            {bullets.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 whitespace-pre-wrap text-sm text-slate-200">
            {bullets[0] || call.summary || emptySummary(call.status)}
          </p>
        )}
      </section>

      <section>
        <h3 className="text-xs uppercase tracking-wide text-slate-400">Action Items</h3>
        <ul className="mt-1 list-disc space-y-1 pl-4 text-sm">
          {actionItems.length ? (
            actionItems.map((item, i) => <li key={i}>{String(item)}</li>)
          ) : (
            <li className="list-none pl-0 text-slate-500">No action items identified</li>
          )}
        </ul>
      </section>

      <section>
        <h3 className="text-xs uppercase tracking-wide text-slate-400">Category</h3>
        <p className="mt-1 text-sm">{call.category ?? "-"}</p>
      </section>

      <section>
        <h3 className="text-xs uppercase tracking-wide text-slate-400">QA Scorecard</h3>
        <dl className="mt-1 grid grid-cols-2 gap-2 text-sm">
          {(["empathy", "resolution", "compliance", "overall"] as const).map((key) => (
            <div key={key}>
              <dt className="text-slate-400">{qaLabel(call.vertical, key)}</dt>
              <dd>{String(qa[key] ?? "-")}</dd>
            </div>
          ))}
        </dl>
        {qa.notes != null && String(qa.notes).trim() && (
          <p className="mt-2 rounded bg-slate-950/60 px-2 py-1.5 text-xs text-slate-300">{String(qa.notes)}</p>
        )}
      </section>

      {rationale && (
        <section>
          <h3 className="text-xs uppercase tracking-wide text-slate-400">Sentiment rationale</h3>
          <p className="mt-1 text-sm text-slate-300">{rationale}</p>
        </section>
      )}

      {moments.length > 0 && (
        <section>
          <h3 className="text-xs uppercase tracking-wide text-slate-400">Sentiment moments</h3>
          <ul className="mt-1 space-y-1 text-sm">
            {moments.map((moment, i) => {
              const polarity = momentPolarity(moment);
              return (
                <li key={i} className={`rounded px-2 py-1 ${SENTIMENT_CHIP_CLASSES[polarity]}`}>
                  <span className="text-xs font-semibold uppercase opacity-80">{momentLabel(polarity)}</span>
                  {moment.start_sec != null && (
                    <span className="ml-2 text-xs opacity-80">{moment.start_sec.toFixed(1)}s</span>
                  )}
                  <p className="mt-0.5">{moment.reason ?? "Notable moment"}</p>
                </li>
              );
            })}
          </ul>
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-400">
            {(Object.keys(SENTIMENT_REGION_COLORS) as Array<keyof typeof SENTIMENT_REGION_COLORS>).map((key) => (
              <span key={key} className="inline-flex items-center gap-1">
                <span
                  className="inline-block h-2 w-4 rounded-sm"
                  style={{ backgroundColor: SENTIMENT_REGION_COLORS[key] }}
                />
                {momentLabel(key)}
              </span>
            ))}
          </div>
        </section>
      )}
    </aside>
  );
}
