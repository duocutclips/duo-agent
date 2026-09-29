import { useState } from "react";
import { api } from "../api";
import { CampaignPicker, useCampaignParam } from "../components/CampaignPicker";
import ScriptEditor from "../components/ScriptEditor";
import { Button, Card, Empty, ErrorBanner, Field, Notice, Page } from "../components/ui";
import { CATEGORY_LABEL, fmtDate } from "../format";
import { useAction, useApi } from "../hooks";
import type { Idea, Script } from "../types";

export default function Scripts() {
  const [campaignId, setCampaignId, campaigns] = useCampaignParam();
  const scripts = useApi<Script[]>(campaignId ? `/api/scripts?campaign_id=${campaignId}` : null);
  const ideas = useApi<Idea[]>(campaignId ? `/api/campaigns/${campaignId}/ideas` : null);
  const [ideaId, setIdeaId] = useState("");
  const [target, setTarget] = useState(30);
  const [warning, setWarning] = useState<string | null>(null);
  const action = useAction();
  const ideaById = new Map((ideas.data ?? []).map((i) => [i.id, i]));

  const generate = () =>
    action.run("gen", async () => {
      const r = await api.post<{ script: Script; warning: string | null }>(`/api/ideas/${ideaId}/scripts`, { target_seconds: target });
      setWarning(r.warning);
      await scripts.reload();
    });
  const remove = (id: string) =>
    action.run("del", async () => {
      await api.del(`/api/scripts/${id}`);
      await scripts.reload();
    });

  return (
    <Page title="Scripts" subtitle="Spoken-style narration: hook first, short sentences, payoff, CTA. Speaking time is estimated live.">
      <CampaignPicker value={campaignId} onChange={setCampaignId} campaigns={campaigns} />
      <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
      {warning && <Notice tone="warn">{warning}</Notice>}
      <Card title="Write a script from an idea">
        <div className="row gap">
          <Field label="Idea">
            <select value={ideaId} onChange={(e) => setIdeaId(e.target.value)} style={{ minWidth: 380 }}>
              <option value="">Choose an idea…</option>
              {ideas.data?.map((i) => (
                <option key={i.id} value={i.id}>
                  [{CATEGORY_LABEL[i.category] ?? i.category}] {i.title}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Target">
            <select value={target} onChange={(e) => setTarget(Number(e.target.value))}>
              {[15, 20, 30, 45].map((t) => (
                <option key={t} value={t}>
                  {t} sec
                </option>
              ))}
            </select>
          </Field>
          <Button kind="primary" onClick={generate} disabled={!ideaId} busy={action.busy === "gen"}>
            Generate script
          </Button>
        </div>
      </Card>
      {scripts.data && scripts.data.length === 0 && <Empty>No scripts for this campaign yet.</Empty>}
      {scripts.data?.map((s) => (
        <Card
          key={s.id}
          title={ideaById.get(s.idea_id ?? "")?.title ?? "Script"}
          actions={
            <>
              <span className="muted small">{fmtDate(s.updated_at)}</span>
              <Button kind="ghost" onClick={() => remove(s.id)}>
                Delete
              </Button>
            </>
          }
        >
          <ScriptEditor script={s} onSaved={() => void scripts.reload()} />
        </Card>
      ))}
    </Page>
  );
}
