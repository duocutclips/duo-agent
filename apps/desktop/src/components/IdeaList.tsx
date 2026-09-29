import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, waitForJob } from "../api";
import { CATEGORY_LABEL } from "../format";
import { useAction, useDefaultQuality } from "../hooks";
import type { Idea, Job, Project } from "../types";
import { Badge, Button, Empty, ErrorBanner, Field, JobBar, Notice, Score } from "./ui";

export default function IdeaList({ campaignId, ideas, reload }: { campaignId: string; ideas: Idea[]; reload: () => Promise<void> }) {
  const action = useAction();
  const nav = useNavigate();
  const [count, setCount] = useState(10);
  const [warning, setWarning] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [quality, setQuality] = useDefaultQuality();

  const generate = () =>
    action.run("gen", async () => {
      const r = await api.post<{ ideas: Idea[]; warning: string | null }>(`/api/campaigns/${campaignId}/ideas`, { count });
      setWarning(r.warning);
      setChosen([]);
      await reload();
    });
  const regenerate = (id: string) =>
    action.run("regen:" + id, async () => {
      const r = await api.post<{ idea: Idea; warning: string | null }>(`/api/ideas/${id}/regenerate`);
      setWarning(r.warning);
      await reload();
    });
  const makeVideo = (idea: Idea) =>
    action.run("proj:" + idea.id, async () => {
      const p = await api.post<Project>("/api/projects", { campaign_id: campaignId, idea_id: idea.id });
      nav(`/projects/${p.id}`);
    });
  const batch = () =>
    action.run("batch", async () => {
      const j = await api.post<Job>(`/api/campaigns/${campaignId}/batch`, { idea_ids: chosen, quality });
      await waitForJob(j.id, setJob);
      setJob(null);
      nav("/projects");
    });

  return (
    <div>
      <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
      {warning && <Notice tone="warn">{warning}</Notice>}
      <JobBar job={job} />
      <div className="row gap" style={{ marginBottom: 12 }}>
        <Field label="Number of concepts">
          <input type="number" min={1} max={30} value={count} onChange={(e) => setCount(Number(e.target.value))} style={{ width: 90 }} />
        </Field>
        <Button kind="primary" onClick={generate} busy={action.busy === "gen"}>
          {ideas.length ? "Regenerate all ideas" : "Generate ideas"}
        </Button>
        {ideas.length > 0 && (
          <>
            <Field label="Render quality">
              <select value={quality} onChange={(e) => setQuality(e.target.value as "draft" | "final")}>
                <option value="final">Final</option>
                <option value="draft">Draft (faster)</option>
              </select>
            </Field>
            <Button onClick={batch} busy={action.busy === "batch"} disabled={chosen.length === 0} title="Script, voice, edit, render and QA every selected idea">
              Produce {chosen.length || ""} selected video{chosen.length === 1 ? "" : "s"}
            </Button>
          </>
        )}
      </div>
      {ideas.length === 0 ? (
        <Empty>No ideas yet. Analyse the campaign first for better compliance, then generate ideas.</Empty>
      ) : (
        <div className="grid grid-2">
          {ideas.map((i) => (
            <div key={i.id} className={"idea" + (chosen.includes(i.id) ? " selected" : "")} data-testid="idea-card">
              <div className="row spread">
                <label className="check">
                  <input type="checkbox" checked={chosen.includes(i.id)} onChange={(e) => setChosen(e.target.checked ? [...chosen, i.id] : chosen.filter((x) => x !== i.id))} />
                  <Badge tone="accent">{CATEGORY_LABEL[i.category] ?? i.category}</Badge>
                  <span className="muted small">~{i.est_duration}s</span>
                </label>
                <div className="row gap">
                  <Score value={i.novelty_score} label="Novelty" />
                  <Score value={i.compliance_score} label="Compliance" />
                </div>
              </div>
              <h3>{i.title}</h3>
              <p>
                <strong>Hook:</strong> {i.hook}
              </p>
              <p className="muted">{i.concept}</p>
              <p className="small">
                <strong>Angle:</strong> {i.script_angle}
              </p>
              <p className="small">
                <strong>Gameplay needed:</strong> {i.required_gameplay.join(", ")}
              </p>
              <p className="small">
                <strong>CTA:</strong> {i.cta}
              </p>
              <details className="small">
                <summary className="muted">Compliance checks · {i.generator}</summary>
                <ul>
                  {i.compliance_notes.map((n) => (
                    <li key={n} className={n.startsWith("PASS") ? "qa-pass" : "qa-fail"}>
                      {n}
                    </li>
                  ))}
                </ul>
              </details>
              <div className="row gap" style={{ marginTop: 8 }}>
                <Button kind="primary" onClick={() => makeVideo(i)} busy={action.busy === "proj:" + i.id}>
                  Make video
                </Button>
                <Button onClick={() => regenerate(i.id)} busy={action.busy === "regen:" + i.id}>
                  Regenerate
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
