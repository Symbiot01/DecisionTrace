import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type EntityDetail } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TypeBadge, EntityChip } from "@/components/EntityChip";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { EvidencePanel } from "@/components/EvidencePanel";
import { StatusBadge } from "@/components/StatusBadge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { ExternalLink, ArrowRight, Share2 } from "lucide-react";
import { Link } from "react-router-dom";
import { encodeKey } from "@/lib/api";
import {
  Collapsible, CollapsibleContent, CollapsibleTrigger,
} from "@/components/ui/collapsible";

export default function EntityDetailPage() {
  const { "*": rawKey } = useParams();
  const naturalKey = rawKey ? decodeURIComponent(rawKey) : "";

  const { data, isLoading, error } = useQuery<EntityDetail>({
    queryKey: ["entity", naturalKey],
    queryFn: () => api.getEntity(naturalKey),
    enabled: !!naturalKey,
  });

  if (isLoading) {
    return (
      <div className="p-6 max-w-4xl mx-auto space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-48" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (error) return <div className="p-6 text-destructive">Error: {(error as Error).message}</div>;
  if (!data) return null;

  const { entity, claims, supersession_chain, rename_chain } = data;
  const props = entity.properties as Record<string, unknown>;
  const title = (props.title as string) || (props.name as string) || entity.natural_key;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="space-y-2">
        <div className="flex items-center gap-3 flex-wrap">
          <TypeBadge type={entity.type} />
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <Link
            to={`/graph?center=${encodeKey(entity.natural_key)}`}
            className="text-xs text-primary hover:underline inline-flex items-center gap-1"
          >
            <Share2 className="h-3 w-3" /> View in graph
          </Link>
        </div>
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <code className="font-mono text-xs bg-muted px-2 py-0.5 rounded">{entity.natural_key}</code>
          {entity.url && (
            <a href={entity.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
              GitHub <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      </div>

      {/* Properties */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Properties</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableBody>
              {Object.entries(props).map(([key, value]) => (
                <TableRow key={key}>
                  <TableCell className="font-mono text-xs text-muted-foreground w-48">{key}</TableCell>
                  <TableCell className="text-sm">{String(value ?? "—")}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Supersession chain */}
      {supersession_chain && supersession_chain.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">Supersession Chain</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 flex-wrap">
              {supersession_chain.map((item, i) => (
                <div key={item.natural_key} className="flex items-center gap-2">
                  {i > 0 && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
                  <div className="flex items-center gap-1">
                    <EntityChip naturalKey={item.natural_key} displayName={item.title} type="DesignDecision" />
                    <StatusBadge status={item.status} />
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Rename chain */}
      {rename_chain && rename_chain.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">Rename History</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 flex-wrap">
              {rename_chain.map((item, i) => (
                <div key={item.natural_key} className="flex items-center gap-2">
                  {i > 0 && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
                  <code className="font-mono text-xs bg-muted px-2 py-0.5 rounded">{item.path}</code>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Claims */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">
            Claims ({claims.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {claims.map((claim, i) => (
            <Collapsible key={i}>
              <CollapsibleTrigger className="w-full text-left">
                <div className="flex items-center justify-between p-2 rounded hover:bg-muted/50 transition-colors">
                  <div className="flex items-center gap-2 flex-wrap text-sm">
                    {claim.direction === "outgoing" ? (
                      <>
                        <span className="font-mono text-xs text-primary">{claim.predicate}</span>
                        <ArrowRight className="h-3 w-3 text-muted-foreground" />
                        <EntityChip
                          naturalKey={claim.other_entity.natural_key}
                          type={claim.other_entity.type}
                          displayName={claim.other_entity.title}
                        />
                      </>
                    ) : (
                      <>
                        <EntityChip
                          naturalKey={claim.other_entity.natural_key}
                          type={claim.other_entity.type}
                          displayName={claim.other_entity.title}
                        />
                        <ArrowRight className="h-3 w-3 text-muted-foreground" />
                        <span className="font-mono text-xs text-primary">{claim.predicate}</span>
                      </>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-muted-foreground">
                      {claim.event_time ? new Date(claim.event_time).toLocaleDateString() : ""}
                    </span>
                    <ConfidenceBadge confidence={claim.confidence} />
                  </div>
                </div>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="ml-4 mb-2">
                  <EvidencePanel
                    excerpt={claim.evidence_excerpt}
                    sourceUrl={claim.source_url}
                    confidence={claim.confidence}
                    timestamp={claim.event_time}
                  />
                </div>
              </CollapsibleContent>
            </Collapsible>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
