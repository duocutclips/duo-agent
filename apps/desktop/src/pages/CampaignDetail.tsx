import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import IdeaList from "../components/IdeaList";
import { Badge, Button, Card, Empty, ErrorBanner, Field, Notice, Page } from "../components/ui";
import { fmtDate } from "../format";
import { useAction, useApi } from "../hooks";
import { isTauri, pickFiles } from "../platform";
import type { Analysis, AnalysisItem, Campaign, Idea, Media } from "../types";
import { CampaignForm } from "./Campaigns";

const CATEGORY_NAMES: Record<string, string> = {
  must_include: "Must appear / do",
  must_avoid: "Must NOT appear / do",
  required_wording: "Required wording",
  code: "Codes",
  cta: "Call to action",
  platform: "Platforms",
  length: "Video length",
  audience: "Target audience",
  mechanic: "Game mechanics",
  originality: "Originality",
  footage: "Footage requirements",
  objective: "Objective",
  payout: "Payout",
  other: "Other",
};

function AnalysisView({ analysis }: { analysis: Analysis }) {
  const groups = new Map<string, AnalysisItem[]>();
  for (const it of analysis.items) groups.set(it.category, [...(groups.get(it.category) ?? []), it]);
  const confirmed = analysis.items.filter((i) => i.status === "confirmed").length;
  return (
    <div>
      <p className="muted">
        {confirmed} confirmed requirement(s), {analysis.items.length - confirmed} suggestion(s) · generator: <code>{analysis.generator}</code>
      </p>
      {analysis.warning && <Notice tone="warn">{analysis.warning}</Notice>}
      <div className="grid grid-2">
        <div>
          <p>
            <strong>Game:</strong> {analysis.game || "–"}
          </p>
          <p>
            <strong>Objective:</strong> {analysis.objective || "–"}
          </p>
          <p>
            <strong>Target audience:</strong> {analysis.target_audience || <span className="muted">not stated</span>}
          </p>
        </div>
        <div>
          <p>
            <strong>Recommended length:</strong>{" "}
            {analysis.recommended_min_seconds ?? "?"}–{analysis.recommended_max_seconds ?? "?"}s{" "}
            <Badge tone={analysis.length_is_confirmed ? "good" : "warn"}>{analysis.length_is_confirmed ? "CONFIRMED" : "AI SUGGESTION"}</Badge>
          </p>
          <p>
            <strong>Platforms:</strong> {analysis.platforms.join(", ") || "–"}
          </p>
          <p>
            <strong>Game mechanics:</strong> {analysis.game_mechanics.join(", ") || <span className="muted">none extracted</span>}
          </p>
        </div>
      </div>
      {[...groups.entries()].map(([cat, items]) => (
        <div key={cat}>
          <h3>{CATEGORY_NAMES[cat] ?? cat}</h3>
          <ul className="item-list">
            {items.map((it, idx) => (
              <li key={idx} data-testid={`analysis-${it.status}`}>
                <Badge tone={it.status === "confirmed" ? "good" : "warn"}>{it.status === "confirmed" ? "CONFIRMED REQUIREMENT" : "AI SUGGESTION"}</Badge> {it.text}
                {it.quote && it.quote !== it.text && <div className="quote">“{it.quote}”</div>}
                {it.rationale && <div className="muted small">{it.rationale}</div>}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export default function CampaignDetail() {
  const { id } = useParams();
  const { data: c, error, reload, setData } = useApi<Campaign>(`/api/campaigns/${id}`);
  const ideas = useApi<Idea[]>(`/api/campaigns/${id}/ideas`);
  const media = useApi<Media[]>(`/api/media?campaign_id=${id}`);
  const [tab, setTab] = useState<"brief" | "material" | "analysis" | "ideas" | "json">("material");
  const [pasteName, setPasteName] = useState("");
  const [paste, setPaste] = useState("");
  const [url, setUrl] = useState("");
  const [json, setJson] = useState<string>("");
  const action = useAction();
  const nav = useNavigate();

  if (!c) return <Page title="Campaign">{error ? <ErrorBanner error={error} /> : <p className="muted">Loading…</p>}</Page>;

  const addText = () =>
    action.run("paste", async () => {
      await api.post(`/api/campaigns/${id}/documents/text`, { name: pasteName || "Pasted text", text: paste });
      setPaste("");
      setPasteName("");
      await reload();
    }, "Text added.");
  const addUrl = () =>
    action.run("url", async () => {
      await api.post(`/api/campaigns/${id}/documents/url`, { url });
      setUrl("");
      await reload();
    }, "Page imported.");
  const addFiles = () =>
    action.run("file", async () => {
      const files = await pickFiles(["pdf", "docx", "txt", "md"]);
      for (const f of files) {
        if (f.path) await api.post(`/api/campaigns/${id}/documents/path`, { path: f.path });
        else {
          const form = new FormData();
          form.append("file", f.file as File);
          await api.form(`/api/campaigns/${id}/documents/file`, form);
        }
      }
      await reload();
    }, "Document(s) imported.");
  const removeDoc = (docId: string) =>
    action.run("del:" + docId, async () => {
      await api.del(`/api/documents/${docId}`);
      await reload();
    });
  const analyze = () =>
    action.run("analyze", async () => {
      await api.post(`/api/campaigns/${id}/analyze`, {});
      await reload();
      setTab("analysis");
    });
  const del = () =>
    action.run("delete", async () => {
      if (!window.confirm(`Delete campaign “${c.name}” with its ideas, scripts and projects? Source files are not deleted.`)) return;
      await api.del(`/api/campaigns/${id}`);
      nav("/campaigns");
    });
  const loadJson = () =>
    action.run("json", async () => {
      setJson(JSON.stringify(await api.get(`/api/campaigns/${id}/structured`), null, 2));
      setTab("json");
    });

  return (
    <Page
      title={c.name}
      subtitle={
        <>
          {c.game || "Game not set"} · {c.platforms.join(", ") || "no platforms"} · {c.payout_cpm !== null ? `$${c.payout_cpm} CPM` : "payout not set"}
          {c.url && (
            <>
              {" "}
              · <a href={c.url} target="_blank" rel="noreferrer">campaign page</a>
            </>
          )}
        </>
      }
      actions={
        <>
          <Button onClick={analyze} busy={action.busy === "analyze"} kind="primary">
            Analyse campaign
          </Button>
          <Button kind="danger" onClick={del}>
            Delete
          </Button>
        </>
      }
    >
      <ErrorBanner error={action.error ?? error} onClose={() => action.setError(null)} />
      {action.notice && <Notice tone="good">{action.notice}</Notice>}
      <div className="tabs">
        {(
          [
            ["material", `Material (${c.documents?.length ?? 0})`],
            ["brief", "Campaign fields"],
            ["analysis", "Analysis"],
            ["ideas", `Ideas (${ideas.data?.length ?? 0})`],
          ] as const
        ).map(([k, label]) => (
          <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
        <button className={tab === "json" ? "active" : ""} onClick={loadJson}>
          Structured JSON
        </button>
      </div>

      {tab === "material" && (
        <div className="grid grid-2">
          <Card title="Import campaign material">
            <Field label="Paste text (brief, Discord message, email…)">
              <input value={pasteName} onChange={(e) => setPasteName(e.target.value)} placeholder="Name (optional)" style={{ marginBottom: 6 }} />
              <textarea value={paste} onChange={(e) => setPaste(e.target.value)} placeholder="Paste the campaign brief here" />
            </Field>
            <Button onClick={addText} disabled={!paste.trim()} busy={action.busy === "paste"}>
              Add text
            </Button>
            <hr style={{ borderColor: "var(--line)", margin: "16px 0" }} />
            <Field label="Public URL" hint="Only publicly accessible pages; pages behind a login can't be imported, paste their text instead.">
              <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
            </Field>
            <Button onClick={addUrl} disabled={!url.trim()} busy={action.busy === "url"}>
              Import URL
            </Button>
            <hr style={{ borderColor: "var(--line)", margin: "16px 0" }} />
            <Button onClick={addFiles} busy={action.busy === "file"}>
              Import PDF / DOCX / TXT…
            </Button>
          </Card>
          <Card title="Documents">
            {c.documents && c.documents.length > 0 ? (
              <table>
                <tbody>
                  {c.documents.map((d) => (
                    <tr key={d.id}>
                      <td>
                        <Badge>{d.kind.toUpperCase()}</Badge> {d.name}
                        <div className="muted small">
                          {d.chars.toLocaleString()} characters · {fmtDate(d.created_at)}
                        </div>
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <Button kind="ghost" onClick={() => removeDoc(d.id)}>
                          Remove
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>No documents yet.</Empty>
            )}
            <h3>Source footage for this campaign</h3>
            <p className="muted">
              {media.data?.filter((m) => m.kind === "video").length ?? 0} video(s). <Link to={`/media?campaign=${id}`}>Manage footage →</Link>
            </p>
          </Card>
        </div>
      )}

      {tab === "brief" && (
        <Card title="Campaign fields">
          <CampaignForm
            initial={c}
            submitLabel="Save changes"
            onSaved={(nc) => {
              setData({ ...c, ...nc });
            }}
          />
        </Card>
      )}

      {tab === "analysis" && (
        <Card title="Campaign analysis" actions={<Button onClick={analyze} busy={action.busy === "analyze"}>Re-analyse</Button>}>
          {c.analysis ? <AnalysisView analysis={c.analysis} /> : <Empty>Not analysed yet. Add material, then click “Analyse campaign”.</Empty>}
        </Card>
      )}

      {tab === "ideas" && (
        <Card title="Content ideas">
          <IdeaList campaignId={c.id} ideas={ideas.data ?? []} reload={ideas.reload} />
        </Card>
      )}

      {tab === "json" && (
        <Card title="Structured campaign data">
          <pre>{json}</pre>
        </Card>
      )}
      {!isTauri() && <p className="muted small">Running in a browser: imported files are uploaded to the local backend's library.</p>}
    </Page>
  );
}
