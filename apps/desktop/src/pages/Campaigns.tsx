import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Button, Card, Empty, ErrorBanner, Field, Page } from "../components/ui";
import { fmtDate, lines } from "../format";
import { useAction, useApi } from "../hooks";
import type { Campaign } from "../types";

const PLATFORMS = ["TikTok", "Instagram", "YouTube", "X", "Snapchat", "Facebook"];

export function CampaignForm({ initial, onSaved, submitLabel }: { initial?: Campaign; onSaved: (c: Campaign) => void; submitLabel: string }) {
  const [name, setName] = useState(initial?.name ?? "");
  const [game, setGame] = useState(initial?.game ?? "");
  const [url, setUrl] = useState(initial?.url ?? "");
  const [platforms, setPlatforms] = useState<string[]>(initial?.platforms ?? []);
  const [cpm, setCpm] = useState(initial?.payout_cpm?.toString() ?? "");
  const [objective, setObjective] = useState(initial?.objective ?? "");
  const [requirements, setRequirements] = useState((initial?.requirements ?? []).join("\n"));
  const [restrictions, setRestrictions] = useState((initial?.restrictions ?? []).join("\n"));
  const [goals, setGoals] = useState((initial?.content_goals ?? []).join("\n"));
  const [hooks, setHooks] = useState((initial?.hook_examples ?? []).join("\n"));
  const [codes, setCodes] = useState((initial?.codes ?? []).join(", "));
  const [links, setLinks] = useState((initial?.reference_links ?? []).join("\n"));
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const action = useAction();

  const save = () =>
    action.run("save", async () => {
      const payout = cpm.trim() === "" ? null : Number(cpm);
      if (payout !== null && (Number.isNaN(payout) || payout < 0)) throw new Error("Payout / CPM must be a positive number.");
      const body = {
        name,
        game,
        url,
        platforms,
        payout_cpm: payout,
        objective,
        requirements: lines(requirements),
        restrictions: lines(restrictions),
        content_goals: lines(goals),
        hook_examples: lines(hooks),
        codes: codes.split(",").map((c) => c.trim()).filter(Boolean),
        reference_links: lines(links),
        notes,
      };
      const c = initial ? await api.patch<Campaign>(`/api/campaigns/${initial.id}`, body) : await api.post<Campaign>("/api/campaigns", body);
      onSaved(c);
    }, "Saved.");

  return (
    <div>
      <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
      <div className="grid grid-2">
        <div>
          <Field label="Campaign name *">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Steal A Seed — launch clips" />
          </Field>
          <Field label="Game name">
            <input value={game} onChange={(e) => setGame(e.target.value)} />
          </Field>
          <Field label="Campaign URL">
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
          </Field>
          <Field label="Payout / CPM (USD per 1,000 views)">
            <input value={cpm} onChange={(e) => setCpm(e.target.value)} inputMode="decimal" />
          </Field>
          <Field label="Platforms">
            <div className="row gap">
              {PLATFORMS.map((p) => (
                <label key={p} className="check">
                  <input
                    type="checkbox"
                    checked={platforms.includes(p)}
                    onChange={(e) => setPlatforms(e.target.checked ? [...platforms, p] : platforms.filter((x) => x !== p))}
                  />
                  {p}
                </label>
              ))}
            </div>
          </Field>
          <Field label="Objective / content goal summary">
            <textarea value={objective} onChange={(e) => setObjective(e.target.value)} />
          </Field>
          <Field label="Codes (comma separated)">
            <input value={codes} onChange={(e) => setCodes(e.target.value)} />
          </Field>
        </div>
        <div>
          <Field label="Requirements (one per line)">
            <textarea value={requirements} onChange={(e) => setRequirements(e.target.value)} />
          </Field>
          <Field label="Restrictions (one per line)">
            <textarea value={restrictions} onChange={(e) => setRestrictions(e.target.value)} />
          </Field>
          <Field label="Content goals (one per line)">
            <textarea value={goals} onChange={(e) => setGoals(e.target.value)} />
          </Field>
          <Field label="Hook examples (one per line)">
            <textarea value={hooks} onChange={(e) => setHooks(e.target.value)} />
          </Field>
          <Field label="Reference links (one per line)">
            <textarea value={links} onChange={(e) => setLinks(e.target.value)} />
          </Field>
          <Field label="Notes">
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>
        </div>
      </div>
      <div className="row gap">
        <Button kind="primary" onClick={save} busy={action.busy === "save"} disabled={!name.trim()}>
          {submitLabel}
        </Button>
        {action.notice && <span className="muted">{action.notice}</span>}
      </div>
    </div>
  );
}

export default function Campaigns() {
  const { data, error } = useApi<Campaign[]>("/api/campaigns");
  const [creating, setCreating] = useState(false);
  const nav = useNavigate();
  return (
    <Page
      title="Campaigns"
      subtitle="Create a campaign manually or import the brief (PDF, DOCX, TXT, pasted text, public URL) on its page."
      actions={
        <Button kind="primary" onClick={() => setCreating(!creating)}>
          {creating ? "Cancel" : "New campaign"}
        </Button>
      }
    >
      <ErrorBanner error={error} />
      {creating && (
        <Card title="New campaign">
          <CampaignForm submitLabel="Create campaign" onSaved={(c) => nav(`/campaigns/${c.id}`)} />
        </Card>
      )}
      <Card>
        {data && data.length === 0 ? (
          <Empty>No campaigns yet. Create one, or use “Create demo campaign” on the dashboard.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Campaign</th>
                <th>Game</th>
                <th>Platforms</th>
                <th>CPM</th>
                <th>Docs</th>
                <th>Footage</th>
                <th>Videos</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {data?.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Link to={`/campaigns/${c.id}`}>{c.name}</Link>
                  </td>
                  <td>{c.game || <span className="muted">–</span>}</td>
                  <td>{c.platforms.join(", ") || <span className="muted">–</span>}</td>
                  <td>{c.payout_cpm !== null ? `$${c.payout_cpm}` : "–"}</td>
                  <td>{c.documents?.length ?? 0}</td>
                  <td>{c.media_count ?? 0}</td>
                  <td>{c.project_count ?? 0}</td>
                  <td className="muted">{fmtDate(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </Page>
  );
}
