import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import ForceGraph2D from "react-force-graph-2d";
import { api, type GraphData, encodeKey } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

const NODE_COLORS: Record<string, string> = {
  Commit: "#6b7280",
  PullRequest: "#3b82f6",
  Issue: "#22c55e",
  Discussion: "#8b5cf6",
  DesignDecision: "#f59e0b",
  Component: "#ec4899",
  Person: "#06b6d4",
  FileNode: "#78716c",
  Tag: "#6366f1",
};

const ALL_TYPES = Object.keys(NODE_COLORS);

export default function GraphExplorer() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const centerKey = searchParams.get("center");
  const graphRef = useRef<any>(null);

  const [minConfidence, setMinConfidence] = useState(0);
  const [visibleTypes, setVisibleTypes] = useState<Set<string>>(new Set(ALL_TYPES));

  const { data, isLoading, error } = useQuery<GraphData>({
    queryKey: ["graph", centerKey],
    queryFn: () =>
      centerKey
        ? api.getGraphNeighborhood(centerKey, 2, 80)
        : api.getGraphOverview(100),
  });

  const filteredData = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    const nodes = data.nodes.filter((n) => visibleTypes.has(n.label));
    const nodeIds = new Set(nodes.map((n) => n.id));
    const links = data.edges
      .filter((e) => e.confidence >= minConfidence && nodeIds.has(e.source) && nodeIds.has(e.target))
      .map((e) => ({ ...e, source: e.source, target: e.target }));
    return { nodes, links };
  }, [data, visibleTypes, minConfidence]);

  const handleNodeClick = useCallback(
    (node: any) => {
      navigate(`/entity/${encodeKey(node.id)}`);
    },
    [navigate]
  );

  const handleNodeDblClick = useCallback(
    (node: any) => {
      navigate(`/graph?center=${encodeKey(node.id)}`);
    },
    [navigate]
  );

  const toggleType = (type: string) => {
    setVisibleTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

  useEffect(() => {
    if (graphRef.current && filteredData.nodes.length > 0) {
      setTimeout(() => graphRef.current?.zoomToFit?.(300, 40), 500);
    }
  }, [filteredData]);

  if (isLoading) return <div className="p-6"><Skeleton className="h-[500px]" /></div>;
  if (error) return <div className="p-6 text-destructive">Failed to load graph: {(error as Error).message}</div>;

  return (
    <div className="flex h-[calc(100vh-3rem)]">
      {/* Filters sidebar */}
      <div className="w-56 border-r p-4 space-y-4 overflow-auto shrink-0">
        <div>
          <h3 className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">Node Types</h3>
          <div className="space-y-2">
            {ALL_TYPES.map((type) => (
              <div key={type} className="flex items-center gap-2">
                <Checkbox
                  id={type}
                  checked={visibleTypes.has(type)}
                  onCheckedChange={() => toggleType(type)}
                />
                <Label htmlFor={type} className="text-sm flex items-center gap-2 cursor-pointer">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: NODE_COLORS[type] }} />
                  {type}
                </Label>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h3 className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">Min Confidence</h3>
          <Slider
            value={[minConfidence]}
            onValueChange={([v]) => setMinConfidence(v)}
            min={0}
            max={1}
            step={0.1}
          />
          <span className="text-xs font-mono text-muted-foreground">{Math.round(minConfidence * 100)}%</span>
        </div>
        {data?.metadata && (
          <Card>
            <CardContent className="p-3 text-xs text-muted-foreground space-y-1">
              <div>Nodes: {data.metadata.total_nodes}</div>
              <div>Edges: {data.metadata.total_edges}</div>
              {data.metadata.sampled && <div className="text-warning">Sampled</div>}
            </CardContent>
          </Card>
        )}
      </div>

      {/* Graph */}
      <div className="flex-1 relative bg-muted/20">
        {centerKey && (
          <div className="absolute top-3 left-3 z-10">
            <button
              onClick={() => navigate("/graph")}
              className="text-xs bg-card border rounded px-2 py-1 hover:bg-accent transition-colors"
            >
              ← Overview
            </button>
          </div>
        )}
        <ForceGraph2D
          ref={graphRef}
          graphData={filteredData}
          nodeLabel={(node: any) => `${node.label}: ${node.title || node.id}`}
          nodeColor={(node: any) => NODE_COLORS[node.label] || "#999"}
          nodeRelSize={4}
          nodeVal={(node: any) => Math.max(1, Math.sqrt(node.degree || 1))}
          linkLabel={(link: any) => `${link.type} (${Math.round(link.confidence * 100)}%)`}
          linkColor={() => "hsl(214 20% 70%)"}
          linkWidth={1}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          onNodeClick={handleNodeClick}
          onNodeDragEnd={() => {}}
          enableNodeDrag
          cooldownTicks={100}
          width={undefined}
          height={undefined}
        />
      </div>
    </div>
  );
}
