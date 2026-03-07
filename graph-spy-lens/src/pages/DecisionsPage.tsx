import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type DecisionsResponse } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { EntityChip } from "@/components/EntityChip";
import { EvidencePanel } from "@/components/EvidencePanel";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ChevronLeft, ChevronRight } from "lucide-react";

export default function DecisionsPage() {
  const [status, setStatus] = useState<string>("");
  const [component, setComponent] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 20;

  const { data, isLoading, error } = useQuery<DecisionsResponse>({
    queryKey: ["decisions", status, component, offset],
    queryFn: () =>
      api.getDecisions({
        status: status || undefined,
        component: component || undefined,
        limit,
        offset,
      }),
  });

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Design Decisions</h1>
        <p className="text-sm text-muted-foreground mt-1">Chronological timeline of architectural decisions</p>
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <Select value={status} onValueChange={(v) => { setStatus(v === "all" ? "" : v); setOffset(0); }}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="All statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="accepted">Accepted</SelectItem>
            <SelectItem value="superseded">Superseded</SelectItem>
            <SelectItem value="proposed">Proposed</SelectItem>
          </SelectContent>
        </Select>
        <Input
          placeholder="Filter by component..."
          value={component}
          onChange={(e) => { setComponent(e.target.value); setOffset(0); }}
          className="w-56"
        />
      </div>

      {isLoading && (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-28" />)}
        </div>
      )}

      {error && <div className="text-destructive text-sm">Error: {(error as Error).message}</div>}

      {data && (
        <>
          {/* Timeline */}
          <div className="relative">
            <div className="absolute left-4 top-0 bottom-0 w-px bg-border" />
            <div className="space-y-4">
              {data.decisions.map((d) => (
                <div key={d.natural_key} className="relative pl-10">
                  <div className="absolute left-3 top-4 w-2.5 h-2.5 rounded-full border-2 border-border bg-card" />
                  <Card>
                    <CardContent className="p-4 space-y-2">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <EntityChip naturalKey={d.natural_key} displayName={d.title} type="DesignDecision" />
                          <div className="text-xs text-muted-foreground mt-1">
                            {new Date(d.event_time).toLocaleDateString()}
                          </div>
                        </div>
                        <StatusBadge status={d.status} />
                      </div>

                      <EvidencePanel
                        excerpt={d.evidence_excerpt}
                        sourceUrl={d.source_url}
                        sourceKey={d.source_key}
                      />

                      <div className="flex items-center gap-2 flex-wrap">
                        {d.components.map((c) => (
                          <EntityChip key={c} naturalKey={c} type="Component" />
                        ))}
                        {d.supersedes && (
                          <span className="text-xs text-muted-foreground">
                            Supersedes: <EntityChip naturalKey={d.supersedes} type="DesignDecision" />
                          </span>
                        )}
                        {d.superseded_by && (
                          <span className="text-xs text-muted-foreground">
                            Superseded by: <EntityChip naturalKey={d.superseded_by} type="DesignDecision" />
                          </span>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                </div>
              ))}
            </div>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {offset + 1}–{Math.min(offset + limit, data.total)} of {data.total}
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>
                <ChevronLeft className="h-4 w-4" /> Prev
              </Button>
              <Button variant="outline" size="sm" disabled={offset + limit >= data.total} onClick={() => setOffset(offset + limit)}>
                Next <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
