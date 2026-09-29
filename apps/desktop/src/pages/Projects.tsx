import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { CampaignPicker, useCampaignParam } from "../components/CampaignPicker";
import { Badge, Button, Card, Empty, ErrorBanner, Page, StatusBadge } from "../components/ui";
import { fmtDate } from "../format";
import { useAction, useApi } from "../hooks";
import type { Idea, Project } from "../types";

interface VariationReport {
  videos: number;
  pairs: { a: string; b: string; same_hook: boolean; script_overlap: number; footage_overlap: number; sfx_overlap: number; same_template: boolean }[];
  max_script_overlap: number;
  max_footage_overlap: number;
  duplicate_hooks: number;
}

export default function Projects() {
  const [campaignId, setCampaignId, campaigns] = useCampaignParam();
  const projects = useApi<Project[]>(campaignId ? `/api/projects?campaign_id=${campaignId}` : null);
  const ideas = useApi<Idea[]>(campaignId ? `/api/campaigns/${campaignId}/ideas` : null);
  const [ideaId, setIdeaId] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [report, setReport] = useState<VariationReport | null>(null);
  const action = useAction();
  const nav = useNavigate();

  const create = () =>
    action.run("create", async () => {
      const p = await api.post<Project>("/api/projects", { campaign_id: campaignId, idea_id: ideaId || null });
      nav(`/projects/${p.id}`);
    });
  const compare = () =>
    action.run("compare", async () => setReport(await api.get<VariationReport>(`/api/projects/variation-report?ids=${selected.join(",")}`)));
  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  return (
    <Page title="Projects" subtitle="One project = one short video moving through script, voice, edit, QA and approval.">
      <CampaignPicker value={campaignId} onChange={setCampaignId} campaigns={campaigns} />
      <ErrorBanner error={action.error ?? projects.error} onClose={() => action.setError(null)} />
      <Card title="New video project">
        <div className="row gap">
          <select value={ideaId} onChange={(e) => setIdeaId(e.target.value)} style={{ minWidth: 380 }} aria-label="idea">
            <option value="">Choose an idea…</option>
            {ideas.data?.map((i) => (
              <option key={i.id} value={i.id}>
                {i.title}
              </option>
            ))}
          </select>
          <Button kind="primary" onClick={create} disabled={!campaignId || !ideaId} busy={action.busy === "create"}>
            Create project
          </Button>
        </div>
      </Card>
      <Card
        title="Videos"
        actions={
          <Button onClick={compare} disabled={selected.length < 2} busy={action.busy === "compare"} title="Check that selected variations differ meaningfully">
            Compare selected ({selected.length})
          </Button>
        }
      >
        {projects.data && projects.data.length === 0 ? (
          <Empty>No projects for this campaign yet. Pick an idea above, or batch-generate from the Ideas page.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th />
                <th>Video</th>
                <th>Status</th>
                <th>QA</th>
                <th>Template</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {projects.data?.map((p) => (
                <tr key={p.id}>
                  <td>
                    <input type="checkbox" checked={selected.includes(p.id)} onChange={() => toggle(p.id)} aria-label={`select ${p.title}`} />
                  </td>
                  <td>
                    <Link to={`/projects/${p.id}`}>{p.title}</Link>
                  </td>
                  <td>
                    <StatusBadge status={p.status} />
                  </td>
                  <td>{p.qa ? <Badge tone={p.ready ? "good" : "bad"}>{p.qa.overall}</Badge> : <span className="muted">not run</span>}</td>
                  <td>{p.template_id}</td>
                  <td className="small muted">{fmtDate(p.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {report && (
        <Card title={`Variation report (${report.videos} videos)`} actions={<Button kind="ghost" onClick={() => setReport(null)}>Close</Button>}>
          <p className="muted small">
            Overlap is word/footage/SFX Jaccard similarity between pairs. Lower is more distinct. Duplicate hooks: {report.duplicate_hooks}.
          </p>
          <table>
            <thead>
              <tr>
                <th>Pair</th>
                <th>Same hook</th>
                <th>Script</th>
                <th>Footage</th>
                <th>SFX</th>
                <th>Same template</th>
              </tr>
            </thead>
            <tbody>
              {report.pairs.map((r) => (
                <tr key={r.a + r.b}>
                  <td className="small">
                    {r.a} ↔ {r.b}
                  </td>
                  <td>{r.same_hook ? <Badge tone="bad">yes</Badge> : "no"}</td>
                  <td>{r.script_overlap.toFixed(2)}</td>
                  <td>{r.footage_overlap.toFixed(2)}</td>
                  <td>{r.sfx_overlap.toFixed(2)}</td>
                  <td>{r.same_template ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </Page>
  );
}
