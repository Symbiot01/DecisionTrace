import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { encodeKey } from "@/lib/api";

interface EntityChipProps {
  naturalKey: string;
  type?: string;
  displayName?: string;
}

const typeColors: Record<string, string> = {
  Commit: "bg-muted text-muted-foreground",
  PullRequest: "bg-primary/10 text-primary",
  Issue: "bg-success/10 text-success",
  Discussion: "bg-info/10 text-info",
  DesignDecision: "bg-warning/10 text-warning",
  Component: "bg-accent text-accent-foreground",
  Person: "bg-secondary text-secondary-foreground",
  FileNode: "bg-muted text-muted-foreground",
  Tag: "bg-primary/10 text-primary",
};

export function EntityChip({ naturalKey, type, displayName }: EntityChipProps) {
  return (
    <Link to={`/entity/${encodeKey(naturalKey)}`}>
      <Badge
        variant="outline"
        className={`cursor-pointer hover:opacity-80 transition-opacity font-mono text-xs ${type ? typeColors[type] || "" : ""}`}
      >
        {displayName || naturalKey}
      </Badge>
    </Link>
  );
}

export function TypeBadge({ type }: { type: string }) {
  return (
    <Badge variant="outline" className={`font-mono text-xs ${typeColors[type] || ""}`}>
      {type}
    </Badge>
  );
}
