import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";

export default function DesignPage() {
  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Grounded Long Term Memory System</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Design and implementation for the Layer10 take home task
        </p>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base font-medium">System Overview</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          <p className="mb-4">
            This document describes the design and implementation of a grounded long term memory system built for the Layer10 take home task.
            This write up explains:
          </p>
          <ul className="list-disc list-inside space-y-1 mb-4">
            <li>Corpus selection and reproducibility</li>
            <li>Ontology and structured extraction</li>
            <li>Evidence grounding</li>
            <li>Deduplication and canonicalization</li>
            <li>Update and revision semantics</li>
            <li>Retrieval and grounding guarantees</li>
            <li>Visualization</li>
            <li>Adaptation to Layer10&apos;s target environment</li>
          </ul>
        </CardContent>
      </Card>

      <ScrollArea className="h-[calc(100vh-18rem)] mt-6">
        <div className="pr-4 space-y-6 text-sm">
          <Section title="1. Public Corpus" id="corpus">
            <SubSection title="Corpus Selection">
              <p>The system uses open source GitHub repository data as its corpus. The default repository is <code className="bg-muted px-1 rounded">567-labs/instructor</code>, configurable via <code className="bg-muted px-1 rounded">TARGET_REPO</code> in <code className="bg-muted px-1 rounded">layerten/config.py</code>. The goal is to simulate a long lived knowledge source with decisions, discussions, code evolution, and collaboration history.</p>
            </SubSection>
            <SubSection title="Data Sources">
              <p>Data is collected using GitHub REST API, GitHub GraphQL API, and local Git clone. Artifacts: Commits (SHA, message, author/committer, parent SHAs, diffs, renames), Pull Requests (title, description, state, branches, comments, reviews, timeline, merge commit), Issues (title, body, labels, assignees, comments, timeline), Discussions (category, body, comments, replies), plus branches, labels, releases, tags.</p>
            </SubSection>
            <SubSection title="Raw Event Storage">
              <p>All fetched artifacts are stored as append only events in <code className="bg-muted px-1 rounded">data/raw_events/events.jsonl</code>. Each entry has <code className="bg-muted px-1 rounded">event_type</code>, <code className="bg-muted px-1 rounded">artifact_id</code>, <code className="bg-muted px-1 rounded">source</code>, <code className="bg-muted px-1 rounded">payload</code>, <code className="bg-muted px-1 rounded">fetched_at</code>. This file is the immutable source of truth.</p>
            </SubSection>
            <SubSection title="Reproducing the Corpus">
              <p>Requirements: Python 3.11+, <code className="bg-muted px-1 rounded">GITHUB_TOKEN</code> in .env. Run: <code className="bg-muted px-1 rounded">pip install -r requirements.txt</code> and <code className="bg-muted px-1 rounded">python -m layerten.fetch.bootstrap</code>. The script clones the repo to <code className="bg-muted px-1 rounded">data/repo</code>, fetches metadata via APIs, and writes to <code className="bg-muted px-1 rounded">events.jsonl</code>. Incremental fetching uses <code className="bg-muted px-1 rounded">get_fetched_ids()</code> for idempotent, resumable ingestion.</p>
              <p className="mt-2 text-muted-foreground italic">Note: Data has already been fetched in the repo; you don&apos;t need to fetch it again.</p>
            </SubSection>
          </Section>

          <Section title="2. Structured Extraction" id="extraction">
            <SubSection title="Ontology">
              <p className="font-medium mb-1">Entity types:</p>
              <p className="text-muted-foreground">Repository, Person, FileNode, Component, Commit, Branch, PullRequest, Issue, Discussion, Review, Label, DesignDecision, Tag, Evidence.</p>
              <p className="font-medium mt-3 mb-1">Relationship types:</p>
              <p className="text-muted-foreground">MODIFIES, CLOSES, REFERENCES, AUTHORED_BY, REVIEWED_BY, ASSIGNED_TO, INTRODUCES, REVERTS, DEPRECATES, DEPENDS_ON, BELONGS_TO, DECISION_FOR, SUPERSEDES, RENAMES, MERGED_INTO, CHERRY_PICKED_FROM, REBASE_OF, ON_BRANCH, STATE_CHANGED_TO.</p>
              <p className="mt-2">Schema enforced by <code className="bg-muted px-1 rounded">layerten/process/tools/validator.py</code>; nodes/relationships outside the schema are rejected.</p>
            </SubSection>
          </Section>

          <Section title="3. Evidence Grounding" id="grounding">
            <p>Every claim must contain: evidence excerpt, source identifier, optional timestamp. Neo4j stores <code className="bg-muted px-1 rounded">evidence_excerpt</code>, <code className="bg-muted px-1 rounded">evidence_source</code>, <code className="bg-muted px-1 rounded">confidence</code>, <code className="bg-muted px-1 rounded">event_time</code>. Sources are mapped to GitHub URLs in <code className="bg-muted px-1 rounded">layerten/api/retrieval/formatter.py</code>. Every memory item is traceable to its origin.</p>
          </Section>

          <Section title="4. Validation Rules" id="validation">
            <p>Schema: all labels and relationship types must match the ontology. Evidence: every claim must include a non empty evidence excerpt. Confidence: claims must have <code className="bg-muted px-1 rounded">confidence ≥ 0.4</code>; lower confidence claims are rejected.</p>
          </Section>

          <Section title="5. Extraction Versioning" id="versioning">
            <p>Extraction depends on prompt, model version, and schema. Conceptually <code className="bg-muted px-1 rounded">extraction_version = hash(prompt + model + schema)</code>. When extraction logic changes, the pipeline can be rerun from raw events. Checkpointing supports incremental processing.</p>
          </Section>

          <Section title="6. Deduplication Strategy" id="dedup">
            <p><strong>Artifact deduplication:</strong> natural keys: Commit (SHA), PR (number), Issue (number), Tag (name). Events from different sources are merged into one artifact. <strong>Reference deduplication:</strong> repeated refs (e.g. closes #123) deduplicated by (type, target); evidence count is tracked.</p>
          </Section>

          <Section title="7. Entity Canonicalization" id="canonical">
            <p><strong>Persons:</strong> GitHub login, email, author name merged; canonical id <code className="bg-muted px-1 rounded">person:&lt;github_login&gt;</code>; aliases preserved. <strong>Files:</strong> path based; renames tracked with RENAMES. <strong>Branches:</strong> by name; deleted branches from PRs kept as ghost branches. <strong>Design decisions:</strong> deduped via graph query; SUPERSEDES for replacements.</p>
          </Section>

          <Section title="8. Claim Deduplication" id="claimdedup">
            <p>Relationships use Neo4j <code className="bg-muted px-1 rounded">MERGE (subject)-[predicate]-&gt;(object)</code>. Identical claims stored once; repeated evidence updates the same relationship.</p>
          </Section>

          <Section title="9. Conflicts and Revisions" id="conflicts">
            <p><strong>Supersession:</strong> outdated claims can be SUPERSEDED by new ones; history preserved. <strong>Conflict detection:</strong> when (subject, predicate) points to multiple objects, conflicts are returned to the user instead of being silently resolved.</p>
          </Section>

          <Section title="10. Reversibility" id="reversibility">
            <p><strong>Immutable raw events:</strong> raw event log is append only; original data never modified. <strong>Merge logs:</strong> dedup/merge operations recorded in <code className="bg-muted px-1 rounded">data/unified/merge_log.jsonl</code>.</p>
          </Section>

          <Section title="11. Memory Graph Design" id="graph">
            <p>Neo4j. Nodes: commits, PRs, issues, contributors, design decisions. Relationships: structured claims with evidence, timestamps, confidence.</p>
          </Section>

          <Section title="12. Temporal Model" id="temporal">
            <p><strong>Event time:</strong> when the event occurred in repo history. <strong>Validity time:</strong> whether the claim is current. Superseded claims remain for historical reasoning.</p>
          </Section>

          <Section title="13. Retrieval Pipeline" id="retrieval">
            <p><strong>Step 1: Query parsing:</strong> keywords, entity refs, intent. <strong>Step 2: Candidate recall:</strong> natural key lookup, Neo4j full text search, text fallback. <strong>Step 3: Graph expansion:</strong> bounded traversal depth. <strong>Step 4: Ranking:</strong> keyword relevance, confidence, recency, match strength; top items returned.</p>
          </Section>

          <Section title="14. Evidence Based Responses" id="responses">
            <p>Every answer includes excerpt, source_key, source_url, timestamp, confidence so responses are grounded in the corpus.</p>
          </Section>

          <Section title="15. Visualization" id="viz">
            <p>Graph exploration, entity inspection, evidence viewing, supersession chains, rename tracking. UI: graph spy lens.</p>
          </Section>

          <Section title="16. Adaptation to Layer10" id="layer10">
            <p>The system is designed to extend beyond GitHub to Layer10&apos;s target environment: Slack/Teams, email, docs, and structured systems like Jira/Linear. Below is how we would adapt the ontology, extraction, dedup, grounding, and operations.</p>
            <SubSection title="Ontology mapping">
              <p>Map current concepts to enterprise sources: <strong>Repository</strong> to Organization or Workspace. <strong>PullRequest / Issue</strong> to Jira or Linear ticket (same lifecycle: open to review to closed/merged). <strong>Discussion</strong> to Slack thread or email thread. <strong>Review / Comment</strong> to Jira comment, Slack reply, or email reply; approval signals from Slack reactions or Jira workflow. <strong>Commit / Diff</strong> to doc revision or page version (no SHA; use version ID). <strong>FileNode</strong> to Document, Confluence page, or wiki page. <strong>Branch</strong> to Sprint or project phase for temporal scoping. <strong>Component</strong> to Jira project, Slack channel, or team; often explicit in Jira, inferred in Slack.</p>
            </SubSection>
            <SubSection title="Extraction per source">
              <p><strong>Slack:</strong> Ingest via Events API; treat threads as first class; use reactions (e.g. thumbs up, eyes) as lightweight approval/attention signals; track message_changed and message_deleted so edits/deletes become events and original text stays in the raw log for grounding. <strong>Email:</strong> Parse MIME; use In Reply To and References for threading; strip signatures and detect quoted/forwarded blocks to deduplicate and attribute correctly. <strong>Jira/Linear:</strong> Structured fields (status, assignee, sprint, components) are extracted deterministically; rich text in descriptions and comments still needs semantic extraction for decisions and rationale. <strong>Docs (Notion, Confluence, Google Docs):</strong> Use version history APIs for event time; treat comments and collaboration as evidence sources; map workspace to page to section as a containment hierarchy.</p>
            </SubSection>
            <SubSection title="Deduplication and identity">
              <p><strong>Artifact dedup:</strong> Slack: dedupe by message permalink; detect edit chains so we don&apos;t store every edit as a new artifact. Email: MinHash or similar on body text to find near duplicates from forwarding/quoting. Jira: one ticket key = one artifact; comments are sub artifacts keyed by id. <strong>Cross platform identity:</strong> Build an identity graph linking Slack user ID, Jira user, email address, and display name (e.g. via SSO, admin mapping, or fuzzy matching). Canonical identifier (e.g. email or internal ID) with aliases; same person in Slack and Jira maps to one Person node. <strong>Same topic across tools:</strong> When the same decision or topic appears in Slack, then a Jira ticket, then email, dedupe by semantic similarity and temporal proximity and merge evidence onto one claim or decision node.</p>
            </SubSection>
            <SubSection title="Grounding and permissions">
              <p>Every claim continues to point to a <strong>source id + excerpt + permalink</strong>. For Slack: message permalink; for Jira: ticket + comment URL; for email: message id and optional attachment/thread link. When a message or doc is <strong>deleted or redacted</strong>, keep the raw event for audit but mark evidence as redacted and flag claims that rely only on redacted evidence. <strong>Permissions:</strong> At retrieval time, filter by the user&apos;s allowed sources (e.g. only channels they can see, only Jira projects they have access to) so memory is scoped to what they can access.</p>
            </SubSection>
            <SubSection title="Long term memory and operations">
              <p><strong>Durable vs ephemeral:</strong> Treat as durable: explicit decisions with rationale, ownership and assignments, status transitions, and facts confirmed by multiple sources. Treat as ephemeral: casual chat without decisions, scheduling, low confidence single source claims. <strong>Preventing drift:</strong> Optional confidence decay for claims not reconfirmed; reconciliation jobs that compare graph state to current system state (e.g. Jira assignee, Slack channel topic) and flag divergence. <strong>Scaling:</strong> Keep Neo4j (or equivalent) for the graph; raw event log in a scalable append store (e.g. S3, Postgres); extraction workers scale horizontally. <strong>Evaluation:</strong> Maintain a golden set of (entity, claim, evidence) triples and run regression tests when changing extraction or dedup logic.</p>
            </SubSection>
          </Section>

          <Section title="17. Summary" id="summary">
            <p>The system implements a grounded long term memory graph that: ingests structured artifact events; extracts knowledge with a typed ontology; grounds claims with evidence; deduplicates entities and artifacts; models evolving decisions; enables evidence backed retrieval. The design ensures reproducibility, traceability, conflict transparency, and extensibility to enterprise communication systems.</p>
          </Section>
        </div>
      </ScrollArea>
    </div>
  );
}

function Section({ title, id, children }: { title: string; id: string; children: React.ReactNode }) {
  return (
    <section id={id} className="space-y-2">
      <h2 className="text-base font-semibold text-foreground scroll-mt-6">{title}</h2>
      <div className="text-muted-foreground space-y-2">{children}</div>
    </section>
  );
}

function SubSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-sm font-medium text-foreground/90">{title}</h3>
      <div className="mt-1">{children}</div>
    </div>
  );
}
