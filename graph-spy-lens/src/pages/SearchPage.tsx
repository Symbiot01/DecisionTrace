import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type SearchResponse } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { EntityChip } from "@/components/EntityChip";
import { EvidencePanel } from "@/components/EvidencePanel";
import { Search, Share2 } from "lucide-react";
import { Link } from "react-router-dom";
import { encodeKey } from "@/lib/api";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [minConfidence, setMinConfidence] = useState(0.4);

  const { data, isLoading, error } = useQuery<SearchResponse>({
    queryKey: ["search", submitted, minConfidence],
    queryFn: () => api.query(submitted, 10, minConfidence),
    enabled: submitted.length > 0,
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) setSubmitted(query.trim());
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Search</h1>
        <p className="text-sm text-muted-foreground mt-1">Ask questions about the codebase</p>
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Why did we switch to Pydantic V2?"
            className="pl-9"
          />
        </div>
        <Button type="submit" disabled={!query.trim()}>Search</Button>
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
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-32" />)}
        </div>
      )}

      {error && <div className="text-destructive text-sm">Error: {(error as Error).message}</div>}

      {data && (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            {data.metadata.returned} results from {data.metadata.candidates_found} candidates · {data.metadata.processing_ms}ms
          </p>

          {data.results.map((r) => (
            <Card key={r.rank}>
              <CardContent className="p-4 space-y-3">
                {/* Claim (optional when result is node-only) */}
                <div className="flex items-start justify-between gap-2">
                  <div className="space-y-1">
                    {r.claim ? (
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-sm">{r.claim.subject_key}</span>
                        <span className="text-muted-foreground text-xs">→</span>
                        <span className="font-mono text-xs text-primary">{r.claim.predicate}</span>
                        <span className="text-muted-foreground text-xs">→</span>
                        <span className="font-mono text-sm">{r.claim.object_key}</span>
                      </div>
                    ) : null}
                    {r.subject_entity.title && (
                      <p className="text-sm text-foreground">{r.subject_entity.title}</p>
                    )}
                  </div>
                  {r.claim && <ConfidenceBadge confidence={r.claim.confidence} />}
                </div>

                {/* Evidence */}
                {r.evidence && (r.evidence.excerpt || r.evidence.source_url) && (
                  <EvidencePanel
                    excerpt={r.evidence.excerpt ?? ""}
                    sourceUrl={r.evidence.source_url ?? undefined}
                    sourceKey={r.evidence.source_key}
                    timestamp={r.evidence.timestamp ?? undefined}
                    confidence={r.claim?.confidence}
                  />
                )}

                {/* Supersedes */}
                {r.supersedes && (
                  <div className="text-xs text-muted-foreground border-l-2 border-warning/40 pl-2">
                    Supersedes: <EntityChip naturalKey={r.supersedes.natural_key} displayName={r.supersedes.title} />
                  </div>
                )}

                {/* Linked entities & actions */}
                <div className="flex items-center gap-2 flex-wrap">
                  {r.linked_entities.map((e) => (
                    <EntityChip key={e.natural_key} naturalKey={e.natural_key} type={e.type} displayName={e.display_name} />
                  ))}
                  <Link
                    to={`/graph?center=${encodeKey(r.subject_entity.natural_key)}`}
                    className="ml-auto text-xs text-primary hover:underline inline-flex items-center gap-1"
                  >
                    <Share2 className="h-3 w-3" /> View in graph
                  </Link>
                </div>
              </CardContent>
            </Card>
          ))}

          {data.conflicts.length > 0 && (
            <div className="mt-4">
              <h3 className="text-sm font-medium text-destructive mb-2">Conflicts</h3>
              {data.conflicts.map((c, i) => (
                <Card key={i} className="border-destructive/30">
                  <CardContent className="p-4">
                    <div className="font-mono text-sm">
                      {c.subject_key} → {c.predicate} → conflicting: {c.conflicting_objects.join(", ")}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
