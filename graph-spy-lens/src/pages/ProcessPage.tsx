import { useEffect, useRef, useState } from "react";
import { api, type PipelineJobStatus } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Loader2 } from "lucide-react";

const JOB_KEY = "layerten_pipeline_job_id";

export default function ProcessPage() {
  const [repoUrl, setRepoUrl] = useState("https://github.com/makeplane/plane");
  const [full, setFull] = useState(true);
  const [reset, setReset] = useState(false);
  const [skipAgentic, setSkipAgentic] = useState(false);
  const [maxEvents, setMaxEvents] = useState<string>("");
  const [resumeId, setResumeId] = useState("");
  const [job, setJob] = useState<PipelineJobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef<number | null>(null);

  const running = !!job && !["completed", "failed"].includes(job.status);

  useEffect(() => {
    const saved = localStorage.getItem(JOB_KEY);
    if (saved) {
      setResumeId(saved);
      void attachJob(saved);
    }
    return () => stopPoll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function stopPoll() {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function startPoll(jobId: string) {
    stopPoll();
    pollRef.current = window.setInterval(async () => {
      try {
        const status = await api.getPipelineJob(jobId);
        setJob(status);
        if (status.status === "completed" || status.status === "failed") {
          stopPoll();
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Poll failed");
        stopPoll();
      }
    }, 1000);
  }

  async function attachJob(jobId: string) {
    const id = jobId.trim();
    if (!id) return;
    setError(null);
    try {
      const status = await api.getPipelineJob(id);
      localStorage.setItem(JOB_KEY, id);
      setResumeId(id);
      setJob(status);
      if (!["completed", "failed"].includes(status.status)) {
        startPoll(id);
      }
    } catch (e) {
      localStorage.removeItem(JOB_KEY);
      setError(e instanceof Error ? e.message : "Could not attach to job");
    }
  }

  async function handleStart() {
    setError(null);
    setJob(null);
    setStarting(true);
    try {
      const max = maxEvents.trim() ? Number(maxEvents) : null;
      const { job_id } = await api.startPipelineJob({
        repo_url: repoUrl.trim(),
        full,
        reset,
        skip_agentic: skipAgentic,
        max_events: max && !Number.isNaN(max) ? max : null,
      });
      localStorage.setItem(JOB_KEY, job_id);
      setResumeId(job_id);
      const initial = await api.getPipelineJob(job_id);
      setJob(initial);
      startPoll(job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start job");
    } finally {
      setStarting(false);
    }
  }

  const m = job?.metrics;

  return (
    <div className="p-6 space-y-6 max-w-3xl mx-auto">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Process repo</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Fetch → merge → sort → process into Neo4j Aura, with parallel Gemini extraction.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Target repository</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="repo">GitHub URL or owner/repo</Label>
            <Input
              id="repo"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              disabled={running || starting}
              placeholder="https://github.com/owner/repo"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="max">Max events (optional, process stage)</Label>
            <Input
              id="max"
              type="number"
              min={1}
              value={maxEvents}
              onChange={(e) => setMaxEvents(e.target.value)}
              disabled={running || starting}
              placeholder="Leave empty for all"
            />
          </div>
          <div className="flex flex-col gap-3">
            <label className="flex items-center justify-between gap-3 text-sm">
              <span>Full pipeline (fetch + merge + sort + process)</span>
              <Switch checked={full} onCheckedChange={setFull} disabled={running || starting} />
            </label>
            <label className="flex items-center justify-between gap-3 text-sm">
              <span>Reset Neo4j graph before process</span>
              <Switch checked={reset} onCheckedChange={setReset} disabled={running || starting} />
            </label>
            <label className="flex items-center justify-between gap-3 text-sm">
              <span>Skip agentic Gemini (deterministic only)</span>
              <Switch checked={skipAgentic} onCheckedChange={setSkipAgentic} disabled={running || starting} />
            </label>
          </div>
          <Button onClick={handleStart} disabled={running || starting || !repoUrl.trim()}>
            {(running || starting) && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {running ? "Running…" : starting ? "Starting…" : "Start processing"}
          </Button>

          <div className="pt-2 border-t space-y-2">
            <Label htmlFor="resume">Resume job id (after page reload)</Label>
            <div className="flex gap-2">
              <Input
                id="resume"
                value={resumeId}
                onChange={(e) => setResumeId(e.target.value)}
                placeholder="paste job uuid"
                disabled={running || starting}
              />
              <Button
                type="button"
                variant="secondary"
                disabled={running || starting || !resumeId.trim()}
                onClick={() => void attachJob(resumeId)}
              >
                Attach
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {job && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Pipeline metrics</CardTitle>
            <Badge variant={job.status === "failed" ? "destructive" : "secondary"}>{job.status}</Badge>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="text-sm text-muted-foreground">
              {job.repo} · stage <span className="font-medium text-foreground">{job.stage}</span>
              <div className="font-mono text-xs mt-1 break-all">{job.job_id}</div>
            </div>
            <Progress value={job.progress_pct} />
            <div className="text-xs text-muted-foreground">{job.progress_pct.toFixed(0)}%</div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
              <Metric label="Processed" value={String(m?.events_processed ?? 0)} />
              <Metric label="Skipped" value={String(m?.events_skipped ?? 0)} />
              <Metric label="Agentic OK" value={String(m?.agentic_ok ?? 0)} />
              <Metric label="Agentic fail" value={String(m?.agentic_failed ?? 0)} />
              <Metric label="Rate" value={`${(m?.rate_per_sec ?? 0).toFixed(2)}/s`} />
              <Metric label="Elapsed" value={`${(m?.elapsed_s ?? 0).toFixed(1)}s`} />
            </div>
            {job.error && (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {job.error}
              </div>
            )}
            {job.status === "completed" && (
              <p className="text-sm text-muted-foreground">
                Done. Open Dashboard or Graph Explorer to inspect the graph.
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-card px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-mono font-semibold mt-0.5">{value}</div>
    </div>
  );
}
