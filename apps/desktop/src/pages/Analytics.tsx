import { CampaignPicker, useCampaignParam } from "../components/CampaignPicker";
import { Card, Empty, ErrorBanner, Notice, Page, Stat } from "../components/ui";
import { fmtMoney, fmtNumber } from "../format";
import { useApi } from "../hooks";
import type { Analytics, Group } from "../types";

function GroupTable({ title, rows }: { title: string; rows: Group[] }) {
  return (
    <Card title={title}>
      {rows.length === 0 ? (
        <Empty>No data yet.</Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th>{title.replace(/^By /, "")}</th>
              <th>Posts</th>
              <th>Total views</th>
              <th>Avg views</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((g) => (
              <tr key={g.key}>
                <td className="small">{g.key}</td>
                <td>{g.posts}</td>
                <td>{fmtNumber(g.total_views)}</td>
                <td>{fmtNumber(Math.round(g.avg_views))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export default function AnalyticsPage() {
  const [campaignId, setCampaignId, campaigns] = useCampaignParam();
  const { data, error } = useApi<Analytics>(campaignId ? `/api/analytics?campaign_id=${campaignId}` : "/api/analytics");
  const t = data?.totals;
  return (
    <Page title="Analytics" subtitle="Numbers come from the submission tracker (entered by you or fetched from official APIs). Correlation, not causation.">
      <CampaignPicker value={campaignId} onChange={setCampaignId} campaigns={campaigns} />
      <ErrorBanner error={error} />
      {data?.sample_note && <Notice tone="warn">{data.sample_note}</Notice>}
      <div className="grid grid-6" style={{ marginBottom: 16 }}>
        <Stat label="Posts" value={t?.posts ?? "–"} hint={`${t?.videos ?? 0} distinct videos`} />
        <Stat label="Views" value={fmtNumber(t?.views)} />
        <Stat label="Avg views / post" value={fmtNumber(t ? Math.round(t.avg_views_per_post) : null)} />
        <Stat label="Engagement" value={fmtNumber(t ? t.likes + t.comments + t.shares + t.saves : null)} hint="likes + comments + shares + saves" />
        <Stat label="Earnings" value={fmtMoney(t?.earnings)} />
        <Stat label="Effective CPM" value={t?.effective_cpm != null ? fmtMoney(t.effective_cpm) : "–"} hint="earnings ÷ views × 1000" />
      </div>
      {(data?.best_hook || data?.best_template) && (
        <div className="grid grid-2">
          {data.best_hook && (
            <Card title="Best performing hook so far">
              <p>{data.best_hook.key}</p>
              <p className="muted small">
                {data.best_hook.posts} posts · avg {fmtNumber(Math.round(data.best_hook.avg_views))} views
              </p>
            </Card>
          )}
          {data.best_template && (
            <Card title="Best performing template so far">
              <p>{data.best_template.key}</p>
              <p className="muted small">
                {data.best_template.posts} posts · avg {fmtNumber(Math.round(data.best_template.avg_views))} views
              </p>
            </Card>
          )}
        </div>
      )}
      <div className="grid grid-2">
        <GroupTable title="By hook" rows={data?.by_hook ?? []} />
        <GroupTable title="By template" rows={data?.by_template ?? []} />
        <GroupTable title="By category" rows={data?.by_category ?? []} />
      </div>
    </Page>
  );
}
