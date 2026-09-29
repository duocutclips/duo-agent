import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { CampaignPicker, useCampaignParam } from "../components/CampaignPicker";
import { Badge, Button, Card, Empty, ErrorBanner, Field, Page } from "../components/ui";
import { fmtDate, fmtMoney } from "../format";
import { useAction, useApi } from "../hooks";
import { openExternal } from "../platform";
import type { Submission } from "../types";

const STATUSES = ["PENDING", "SUBMITTED", "APPROVED", "REJECTED", "PAID"];
const METRICS = ["views", "likes", "comments", "shares", "saves"] as const;
const PLATFORMS = ["TikTok", "Instagram", "YouTube", "X", "Snapchat", "Facebook"];

function Row({ s, reload }: { s: Submission; reload: () => Promise<void> }) {
  const [edit, setEdit] = useState(s);
  const action = useAction();
  useEffect(() => setEdit(s), [s]);
  const dirty = JSON.stringify(edit) !== JSON.stringify(s);
  const save = () =>
    action.run("save", async () => {
      await api.patch(`/api/submissions/${s.id}`, {
        status: edit.status,
        earnings: edit.earnings,
        notes: edit.notes,
        ...Object.fromEntries(METRICS.map((m) => [m, edit[m]])),
      });
      await reload();
    });
  const refresh = () =>
    action.run("refresh", async () => {
      await api.post(`/api/submissions/${s.id}/refresh-metrics`);
      await reload();
    });
  const remove = () =>
    action.run("del", async () => {
      if (!window.confirm("Delete this submission record?")) return;
      await api.del(`/api/submissions/${s.id}`);
      await reload();
    });
  return (
    <>
      <tr>
        <td>
          <Badge tone="info">{s.platform}</Badge>
          <div className="small">
            {s.project_id ? <Link to={`/projects/${s.project_id}`}>video</Link> : <span className="muted">no project</span>} ·{" "}
            {s.post_url ? (
              <a href={s.post_url} onClick={(e) => (e.preventDefault(), openExternal(s.post_url))}>
                post
              </a>
            ) : (
              "no link"
            )}
          </div>
          <div className="small muted">{fmtDate(s.submitted_at)}</div>
        </td>
        <td>
          <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })} aria-label="status">
            {STATUSES.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </td>
        {METRICS.map((m) => (
          <td key={m}>
            <input type="number" min={0} value={edit[m]} onChange={(e) => setEdit({ ...edit, [m]: Number(e.target.value) })} style={{ width: 90 }} aria-label={m} />
          </td>
        ))}
        <td>
          <input
            type="number"
            min={0}
            step="0.01"
            value={edit.earnings ?? ""}
            placeholder={s.estimated_earnings != null ? `est. ${s.estimated_earnings.toFixed(2)}` : ""}
            onChange={(e) => setEdit({ ...edit, earnings: e.target.value === "" ? null : Number(e.target.value) })}
            style={{ width: 100 }}
            aria-label="earnings"
          />
          <div className="small muted">{s.effective_cpm != null ? `CPM ${fmtMoney(s.effective_cpm)}` : ""}</div>
        </td>
        <td>
          <div className="row gap">
            <Button kind="primary" onClick={save} disabled={!dirty} busy={action.busy === "save"}>
              Save
            </Button>
            {s.platform === "YouTube" && (
              <Button onClick={refresh} busy={action.busy === "refresh"} title="Fetch views/likes/comments from the YouTube Data API">
                Refresh
              </Button>
            )}
            <Button kind="ghost" onClick={remove}>
              ×
            </Button>
          </div>
        </td>
      </tr>
      {action.error && (
        <tr>
          <td colSpan={9}>
            <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
          </td>
        </tr>
      )}
    </>
  );
}

export default function Submissions() {
  const [campaignId, setCampaignId, campaigns] = useCampaignParam();
  const subs = useApi<Submission[]>(campaignId ? `/api/submissions?campaign_id=${campaignId}` : null);
  const [platform, setPlatform] = useState("TikTok");
  const [url, setUrl] = useState("");
  const action = useAction();
  const add = () =>
    action.run("add", async () => {
      await api.post("/api/submissions", { campaign_id: campaignId, platform, post_url: url || undefined });
      setUrl("");
      await subs.reload();
    });
  return (
    <Page title="Submissions" subtitle="Track every post: link, campaign submission status, views and earnings. Metrics are entered manually unless an official API is connected.">
      <CampaignPicker value={campaignId} onChange={setCampaignId} campaigns={campaigns} />
      <ErrorBanner error={action.error ?? subs.error} onClose={() => action.setError(null)} />
      <Card title="Add a post">
        <p className="muted small">Posts recorded from a project (Export &amp; publish → Mark posted) appear here automatically.</p>
        <div className="row gap">
          <Field label="Platform">
            <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
              {PLATFORMS.map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
          </Field>
          <Field label="Post URL">
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" style={{ minWidth: 360 }} />
          </Field>
          <Button kind="primary" onClick={add} disabled={!campaignId} busy={action.busy === "add"}>
            Add
          </Button>
        </div>
      </Card>
      <Card title="Posts">
        {subs.data && subs.data.length === 0 ? (
          <Empty>No posts tracked for this campaign yet.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Post</th>
                <th>Status</th>
                {METRICS.map((m) => (
                  <th key={m}>{m}</th>
                ))}
                <th>Earnings ($)</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {subs.data?.map((s) => (
                <Row key={s.id} s={s} reload={subs.reload} />
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </Page>
  );
}
