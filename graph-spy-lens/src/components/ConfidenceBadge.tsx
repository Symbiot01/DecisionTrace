import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface ConfidenceBadgeProps {
  confidence: number;
  className?: string;
}

export function ConfidenceBadge({ confidence, className }: ConfidenceBadgeProps) {
  const pct = Math.round(confidence * 100);
  let variant: "default" | "secondary" | "destructive" | "outline" = "default";
  let colorClass = "";

  if (confidence >= 0.8) {
    colorClass = "bg-success text-success-foreground";
  } else if (confidence >= 0.6) {
    colorClass = "bg-warning text-warning-foreground";
  } else {
    colorClass = "bg-destructive text-destructive-foreground";
  }

  return (
    <Badge variant="outline" className={cn("font-mono text-xs border-0", colorClass, className)}>
      {pct}%
    </Badge>
  );
}
