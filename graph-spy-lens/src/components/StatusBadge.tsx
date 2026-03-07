import { Badge } from "@/components/ui/badge";

const statusStyles: Record<string, string> = {
  accepted: "bg-success/10 text-success border-success/20",
  superseded: "bg-muted text-muted-foreground border-border",
  proposed: "bg-warning/10 text-warning border-warning/20",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={`text-xs capitalize ${statusStyles[status] || ""}`}>
      {status}
    </Badge>
  );
}
