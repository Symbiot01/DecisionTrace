import { useQuery } from "@tanstack/react-query";
import { api, type StatsData } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { EntityChip } from "@/components/EntityChip";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { GitCommit, GitPullRequest, MessageSquare, FileCode, Lightbulb, Users, Tag, Box } from "lucide-react";

const nodeIcons: Record<string, React.ReactNode> = {
  Commit: <GitCommit className="h-4 w-4" />,
  PullRequest: <GitPullRequest className="h-4 w-4" />,
  Issue: <MessageSquare className="h-4 w-4" />,
  Discussion: <MessageSquare className="h-4 w-4" />,
  DesignDecision: <Lightbulb className="h-4 w-4" />,
  Component: <Box className="h-4 w-4" />,
  Person: <Users className="h-4 w-4" />,
  FileNode: <FileCode className="h-4 w-4" />,
  Tag: <Tag className="h-4 w-4" />,
};

export default function Dashboard() {
  const { data, isLoading, error } = useQuery<StatsData>({
    queryKey: ["stats"],
    queryFn: api.getStats,
  });

  if (isLoading) return <DashboardSkeleton />;
  if (error) return <div className="p-6 text-destructive">Failed to load stats: {(error as Error).message}</div>;
  if (!data) return null;

  const totalNodes = Object.values(data.nodes).reduce((a, b) => a + b, 0);
  const totalRels = Object.values(data.relationships).reduce((a, b) => a + b, 0);

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground mt-1">Knowledge graph overview</p>
      </div>

      {/* Processing Progress */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Processing Progress</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between text-sm mb-2">
            <span className="text-muted-foreground">
              {data.processing.checkpoint_index.toLocaleString()} / {data.processing.total_events.toLocaleString()} events
            </span>
            <span className="font-mono text-sm">{data.processing.percent_complete.toFixed(1)}%</span>
          </div>
          <Progress value={data.processing.percent_complete} className="h-2" />
        </CardContent>
      </Card>

      {/* Node counts */}
      <div>
        <h2 className="text-sm font-medium text-muted-foreground mb-3">
          Nodes · {totalNodes.toLocaleString()} total
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {Object.entries(data.nodes).map(([type, count]) => (
            <Card key={type}>
              <CardContent className="p-4 flex items-center gap-3">
                <div className="text-muted-foreground">{nodeIcons[type] || <Box className="h-4 w-4" />}</div>
                <div>
                  <div className="text-xl font-semibold font-mono">{count.toLocaleString()}</div>
                  <div className="text-xs text-muted-foreground">{type}</div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      {/* Relationship counts */}
      <div>
        <h2 className="text-sm font-medium text-muted-foreground mb-3">
          Relationships · {totalRels.toLocaleString()} total
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {Object.entries(data.relationships).map(([type, count]) => (
            <Card key={type}>
              <CardContent className="p-4">
                <div className="text-lg font-semibold font-mono">{count.toLocaleString()}</div>
                <div className="text-xs text-muted-foreground font-mono">{type}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      {/* Top connected & files */}
      <div className="grid md:grid-cols-2 gap-6">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">Top Connected Nodes</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Entity</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead className="text-right">Degree</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.top_connected.map((node) => (
                  <TableRow key={node.natural_key}>
                    <TableCell>
                      <EntityChip naturalKey={node.natural_key} type={node.type} />
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{node.type}</TableCell>
                    <TableCell className="text-right font-mono">{node.degree}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">Most Modified Files</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>File</TableHead>
                  <TableHead className="text-right">Commits</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.top_modified_files.map((f) => (
                  <TableRow key={f.path}>
                    <TableCell className="font-mono text-xs">{f.path}</TableCell>
                    <TableCell className="text-right font-mono">{f.commit_count}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-24 w-full" />
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
    </div>
  );
}
