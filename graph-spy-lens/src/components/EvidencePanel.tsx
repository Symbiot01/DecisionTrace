import { ExternalLink } from "lucide-react";
import { ConfidenceBadge } from "./ConfidenceBadge";

interface EvidencePanelProps {
  excerpt?: string | null;
  sourceUrl?: string | null;
  sourceKey?: string;
  timestamp?: string | null;
  confidence?: number;
}

function confidenceLabel(c: number): string {
  if (c >= 1.0) return "Structured";
  if (c >= 0.8) return "Explicit";
  if (c >= 0.6) return "Implied";
  return "Inferred";
}

export function EvidencePanel({ excerpt, sourceUrl, sourceKey, timestamp, confidence }: EvidencePanelProps) {
  const hasContent = (excerpt && excerpt.trim()) || sourceUrl || sourceKey || timestamp || confidence !== undefined;
  if (!hasContent) return null;

  return (
    <div className="border rounded-md p-3 bg-muted/30 space-y-2 text-sm">
      {excerpt?.trim() ? (
        <blockquote className="border-l-2 border-primary/40 pl-3 text-muted-foreground italic">
          {excerpt}
        </blockquote>
      ) : null}
      <div className="flex items-center gap-3 flex-wrap text-xs text-muted-foreground">
        {confidence !== undefined && (
          <span className="flex items-center gap-1">
            <ConfidenceBadge confidence={confidence} />
            <span>{confidenceLabel(confidence)}</span>
          </span>
        )}
        {sourceKey && <span className="font-mono">{sourceKey}</span>}
        {timestamp && <span>{new Date(timestamp).toLocaleDateString()}</span>}
        {sourceUrl && (
          <a
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-primary hover:underline"
          >
            GitHub <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
    </div>
  );
}
