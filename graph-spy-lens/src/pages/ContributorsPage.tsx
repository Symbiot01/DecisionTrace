import { useQuery } from "@tanstack/react-query";
import { api, type ContributorsResponse } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EntityChip } from "@/components/EntityChip";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronDown, ExternalLink } from "lucide-react";

export default function ContributorsPage() {
  const { data, isLoading, error } = useQuery<ContributorsResponse>({
    queryKey: ["contributors"],
    queryFn: () => api.getContributors(30),
  });

  if (isLoading) {
    return (
      <div className="p-6 max-w-5xl mx-auto space-y-3">
        <Skeleton className="h-8 w-48" />
        {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-16" />)}
      </div>
    );
  }

  if (error) return <div className="p-6 text-destructive">Error: {(error as Error).message}</div>;
  if (!data) return null;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Contributors</h1>
        <p className="text-sm text-muted-foreground mt-1">Ranked by total contributions</p>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-8">#</TableHead>
            <TableHead>Contributor</TableHead>
            <TableHead className="text-right">Commits</TableHead>
            <TableHead className="text-right">PRs</TableHead>
            <TableHead className="text-right">Reviews</TableHead>
            <TableHead className="text-right">Issues</TableHead>
            <TableHead className="text-right">Total</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.contributors.map((c, i) => (
            <Collapsible key={c.natural_key} asChild>
              <>
                <TableRow>
                  <TableCell className="font-mono text-muted-foreground">{i + 1}</TableCell>
                  <TableCell>
                    <CollapsibleTrigger className="flex items-center gap-2 hover:text-primary transition-colors">
                      <ChevronDown className="h-3 w-3" />
                      <EntityChip naturalKey={c.natural_key} type="Person" displayName={c.display_name} />
                      {c.url && (
                        <a href={c.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>
                          <ExternalLink className="h-3 w-3 text-muted-foreground hover:text-primary" />
                        </a>
                      )}
                    </CollapsibleTrigger>
                  </TableCell>
                  <TableCell className="text-right font-mono">{c.stats.commits}</TableCell>
                  <TableCell className="text-right font-mono">{c.stats.prs_authored}</TableCell>
                  <TableCell className="text-right font-mono">{c.stats.reviews_given}</TableCell>
                  <TableCell className="text-right font-mono">{c.stats.issues_opened}</TableCell>
                  <TableCell className="text-right font-mono font-semibold">{c.stats.total_contributions}</TableCell>
                </TableRow>
                <CollapsibleContent asChild>
                  <tr>
                    <td colSpan={7} className="p-0">
                      <div className="px-10 py-3 bg-muted/30 border-t">
                        <div className="text-xs text-muted-foreground mb-1">
                          Aliases: {c.aliases.join(", ")}
                        </div>
                        {c.decisions_introduced.length > 0 && (
                          <div className="space-y-1">
                            <div className="text-xs font-medium">Decisions introduced:</div>
                            <div className="flex flex-wrap gap-1">
                              {c.decisions_introduced.map((d) => (
                                <EntityChip key={d.natural_key} naturalKey={d.natural_key} displayName={d.title} type="DesignDecision" />
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                </CollapsibleContent>
              </>
            </Collapsible>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
