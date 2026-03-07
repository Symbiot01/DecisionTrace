import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type AskResponse, type SearchResult } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { EntityChip } from "@/components/EntityChip";
import { EvidencePanel } from "@/components/EvidencePanel";
import { MessageCircle, Share2 } from "lucide-react";
import { Link } from "react-router-dom";
import { encodeKey } from "@/lib/api";

/** Renders answer text with [1], [2] etc. as clickable refs that scroll to the source card */
function AnswerWithCitations({ answer, className = "" }: { answer: string; className?: string }) {
  const parts = answer.split(/(\[\d+\])/g);
  return (
    <div className={`whitespace-pre-wrap text-sm ${className}`}>
      {parts.map((part, i) => {
        const m = part.match(/^\[(\d+)\]$/);
        if (m) {
          const num = m[1];
          return (
            <button
              key={`${i}-${num}`}
              type="button"
              onClick={() => document.getElementById(`source-${num}`)?.scrollIntoView({ behavior: "smooth", block: "center" })}
              className="inline-flex align-baseline justify-center min-w-[1.5rem] h-5 px-1 mx-0.5 rounded bg-primary/15 text-primary font-mono text-xs hover:bg-primary/25 focus:outline-none focus:ring-2 focus:ring-primary/50"
              title={`View source ${num}`}
            >
              {part}
            </button>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </div>
  );
}

function SourceCard({ r }: { r: SearchResult }) {
  return (
    <Card id={`source-${r.rank}`} className="scroll-mt-24">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-start justify-between gap-2">
          <div className="space-y-1">
            <span className="text-xs font-medium text-muted-foreground">Source {r.rank}</span>
            {r.claim ? (
              <div className="flex items-center gap-2 flex-wrap font-mono text-sm">
                <span>{r.claim.subject_key}</span>
                <span className="text-muted-foreground text-xs">→</span>
                <span className="text-primary text-xs">{r.claim.predicate}</span>
                <span className="text-muted-foreground text-xs">→</span>
                <span>{r.claim.object_key}</span>
              </div>
            ) : null}
            {r.subject_entity.title && (
              <p className="text-sm text-foreground">{r.subject_entity.title}</p>
            )}
          </div>
          {r.claim && <ConfidenceBadge confidence={r.claim.confidence} />}
        </div>
        {r.evidence && (r.evidence.excerpt || r.evidence.source_url) && (
          <EvidencePanel
            excerpt={r.evidence.excerpt ?? ""}
            sourceUrl={r.evidence.source_url ?? undefined}
            sourceKey={r.evidence.source_key}
            timestamp={r.evidence.timestamp ?? undefined}
            confidence={r.claim?.confidence}
          />
        )}
        <div className="flex items-center gap-2 flex-wrap">
          {r.linked_entities.map((e) => (
            <EntityChip key={e.natural_key} naturalKey={e.natural_key} type={e.type} displayName={e.display_name} />
          ))}
          <Link
            to={`/entity/${encodeKey(r.subject_entity.natural_key)}`}
            className="text-xs text-primary hover:underline inline-flex items-center gap-1"
          >
            View entity
          </Link>
          <Link
            to={`/graph?center=${encodeKey(r.subject_entity.natural_key)}`}
            className="text-xs text-primary hover:underline inline-flex items-center gap-1"
          >
            <Share2 className="h-3 w-3" /> In graph
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [minConfidence, setMinConfidence] = useState(0.4);

  const { data, isLoading, error } = useQuery<AskResponse>({
    queryKey: ["ask", submitted, minConfidence],
    queryFn: () => api.ask(submitted, 8, minConfidence),
    enabled: submitted.length > 0,
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (question.trim()) setSubmitted(question.trim());
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Ask</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Get an answer grounded in evidence, with citations to sources
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2">
        <div className="relative flex-1">
          <MessageCircle className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Why did we switch to Pydantic V2?"
            className="pl-9"
          />
        </div>
        <Button type="submit" disabled={!question.trim()}>
          Ask
        </Button>
      </form>

      <div className="flex items-center gap-3 text-sm">
        <span className="text-muted-foreground whitespace-nowrap">Min confidence:</span>
        <Slider
          value={[minConfidence]}
          onValueChange={([v]) => setMinConfidence(v)}
          min={0}
          max={1}
          step={0.1}
          className="w-40"
        />
        <span className="font-mono text-xs w-10">{Math.round(minConfidence * 100)}%</span>
      </div>

      {isLoading && (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      )}

      {error && (
        <div className="text-destructive text-sm">Error: {(error as Error).message}</div>
      )}

      {data && (
        <div className="space-y-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Answer</CardTitle>
              <p className="text-xs text-muted-foreground">
                {data.metadata.sources_used} sources · {data.metadata.processing_ms}ms
              </p>
            </CardHeader>
            <CardContent>
              <AnswerWithCitations answer={data.answer} />
              <p className="text-xs text-muted-foreground mt-3">
                Click <span className="font-mono bg-muted px-1 rounded">[1]</span>, <span className="font-mono bg-muted px-1 rounded">[2]</span> to jump to the source below.
              </p>
            </CardContent>
          </Card>

          <div>
            <h2 className="text-sm font-medium text-muted-foreground mb-3">Referenced evidence</h2>
            <div className="space-y-3">
              {data.sources.map((r) => (
                <SourceCard key={r.rank} r={r} />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
