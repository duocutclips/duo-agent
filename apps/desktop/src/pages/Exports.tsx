import { Link } from "react-router-dom";
import { api } from "../api";
import { Button, Card, Empty, ErrorBanner, Page, StatusBadge } from "../components/ui";
import { fmtDate } from "../format";
import { useAction, useApi } from "../hooks";
import type { Project } from "../types";

export default function Exports() {
  const projects = useApi<Project[]>("/api/projects");
  const action = useAction();
  const exported = (projects.data ?? []).filter((p) => p.export_path);
  const waiting = (projects.data ?? []).filter((p) => p.status === "APPROVED" && !p.export_path);
  const open = (path: string) => action.run("open", () => api.post("/api/system/open", { path }));
  return (
    <Page title="Exports" subtitle="Approved videos exported as exports/<campaign>/concept-NN.mp4, each with a caption .txt next to it.">
      <ErrorBanner error={action.error ?? projects.error} onClose={() => action.setError(null)} />
      {waiting.length > 0 && (
        <Card title="Approved, not exported yet">
          <ul className="item-list">
            {waiting.map((p) => (
              <li key={p.id}>
                <Link to={`/projects/${p.id}`}>{p.title}</Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card title={`Exported videos (${exported.length})`}>
        {exported.length === 0 ? (
          <Empty>Nothing exported yet. Approve a video in its project, then export it.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Video</th>
                <th>Status</th>
                <th>File</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {exported.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link to={`/projects/${p.id}`}>{p.title}</Link>
                  </td>
                  <td>
                    <StatusBadge status={p.status} />
                  </td>
                  <td className="mono small">{p.export_path}</td>
                  <td className="small muted">{fmtDate(p.updated_at)}</td>
                  <td>
                    <div className="row gap">
                      <Button kind="ghost" onClick={() => void open(p.export_path!)}>
                        Open
                      </Button>
                      <Button kind="ghost" onClick={() => void open(p.export_path!.replace(/[\\/][^\\/]+$/, ""))}>
                        Folder
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </Page>
  );
}
