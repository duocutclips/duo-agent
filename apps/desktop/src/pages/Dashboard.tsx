import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, waitForJob } from "../api";
import { Button, Card, Empty, ErrorBanner, JobBar, Page, Stat, StatusBadge } from "../components/ui";
import { fmtDate, fmtMoney, fmtNumber } from "../format";
import { useAction, useApi } from "../hooks";
import type { Dashboard, Job } from "../types";

export default function DashboardPage() {
  const { data, error, reload } = useApi<Dashboard>("/api/dashboard");
  const action = useAction();
  const [job, setJob] = useState<Job | null>(null);
  const nav = useNavigate();

  const createDemo = () =>
    action.run("demo", async () => {
      const j = await api.post<Job>("/api/demo");
      const done = await waitForJob(j.id, setJob);
      setJob(null);
      await reload();
      const res = done.result as { campaign_id: string };
      nav(`/campaigns/${res.campaign_id}`);
    });

  return (
    <Page
      title="Dashboard"
      subtitle="Campaign brief → ideas → script → voice → edit → QA → approval → export."
      actions={
        <Button onClick={createDemo} busy={action.busy === "demo"} kind="primary">
          Create demo campaign
        </Button>
      }
    >
      <ErrorBanner error={error ?? action.error} />
      <JobBar job={job} />
      <div className="grid grid-6" style={{ marginBottom: 16 }}>
        <Stat label="Active campaigns" value={data?.active_campaigns ?? "–"} />
        <Stat label="Videos generated" value={data?.videos_generated ?? "–"} />
        <Stat label="Videos ready" value={data?.videos_ready ?? "–"} hint="In review, approved or exported" />
        <Stat label="Videos posted" value={data?.videos_posted ?? "–"} />
        <Stat label="Total views" value={fmtNumber(data?.total_views)} hint="From the submission tracker" />
        <Stat label="Estimated earnings" value={fmtMoney(data?.estimated_earnings)} hint="Entered earnings, else views × CPM" />
      </div>
      <Card title="Recent projects" actions={<Link to="/projects">All projects</Link>}>
        {data && data.recent_projects.length === 0 ? (
          <Empty>
            No projects yet. Create a campaign (or the demo campaign), generate ideas, then turn an idea into a video.
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Video</th>
                <th>Status</th>
                <th>QA</th>
                <th>Template</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {data?.recent_projects.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link to={`/projects/${p.id}`}>{p.title}</Link>
                  </td>
                  <td>
                    <StatusBadge status={p.status} />
                  </td>
                  <td>{p.ready ? <span className="qa-pass">READY</span> : <span className="muted">–</span>}</td>
                  <td className="muted">{p.template_id}</td>
                  <td className="muted">{fmtDate(p.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </Page>
  );
}
