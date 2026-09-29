import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Button, Card, ErrorBanner, Field, Page } from "../components/ui";
import { useAction, useApi } from "../hooks";
import type { IntegrationStatus } from "../types";

interface Health {
  version: string;
  python: string;
  platform: string;
  data_dir: string;
  exports_dir: string;
  logs_dir: string;
  schema_version: number;
}
interface Prefs {
  default_quality: "draft" | "final";
  max_silence_seconds: number;
  use_ai: boolean;
}
type LogLine = { ts?: string; level?: string; logger?: string; msg?: string; [k: string]: unknown };

function Row({ name, ok, text, envs }: { name: string; ok: boolean; text: string; envs: string }) {
  return (
    <tr>
      <td>{name}</td>
      <td>{ok ? <Badge tone="good">ready</Badge> : <Badge tone="warn">not configured</Badge>}</td>
      <td className="small">{text}</td>
      <td className="mono small muted">{envs}</td>
    </tr>
  );
}

export default function SettingsPage() {
  const status = useApi<IntegrationStatus>("/api/status");
  const health = useApi<Health>("/api/health");
  const prefs = useApi<Prefs>("/api/preferences");
  const logs = useApi<LogLine[]>("/api/logs?limit=200");
  const [draft, setDraft] = useState<Prefs | null>(null);
  const action = useAction();
  useEffect(() => setDraft(prefs.data), [prefs.data]);
  const s = status.data;
  const save = () =>
    action.run("prefs", async () => {
      prefs.setData(await api.put<Prefs>("/api/preferences", draft));
    }, "Saved.");
  const openLogs = () => health.data && action.run("open", () => api.post("/api/system/open", { path: health.data!.logs_dir }));

  return (
    <Page title="Settings" subtitle="API keys are read from environment variables (or a local .env file) and are never shown, stored in the database or logged.">
      <ErrorBanner error={action.error ?? status.error} onClose={() => action.setError(null)} />
      <Card title="Integrations" actions={<Button onClick={() => void status.reload()}>Re-check</Button>}>
        {s && (
          <table>
            <thead>
              <tr>
                <th>Service</th>
                <th>State</th>
                <th>Details</th>
                <th>Environment variables</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(s.ffmpeg).map(([k, v]) => (
                <Row key={k} name={k} ok={v.available} text={v.available ? `${v.version ?? ""} (${v.path})` : `Not found at ${v.path}`} envs={k === "ffmpeg" ? "FFMPEG_PATH" : "FFPROBE_PATH"} />
              ))}
              <Row name="Claude (ideas, scripts, analysis)" ok={s.llm.configured} text={s.llm.configured ? `model ${s.llm.model}` : s.llm.message ?? "Offline templates are used instead."} envs="ANTHROPIC_API_KEY, ANTHROPIC_MODEL" />
              <Row name="ElevenLabs voice" ok={s.voice.elevenlabs.configured} text={s.voice.elevenlabs.message ?? "ready"} envs="ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID" />
              <Row name="Offline system voice" ok={s.voice.system.available} text={s.voice.system.message ?? s.voice.system.engine} envs="–" />
              <Row
                name="Transcription (word timing)"
                ok={s.transcription.whisper_api.configured || s.transcription.faster_whisper.installed}
                text={s.transcription.whisper_api.configured ? "Whisper API" : s.transcription.faster_whisper.installed ? "Local faster-whisper" : `Fallback: ${s.transcription.fallback}`}
                envs="WHISPER_API_URL, WHISPER_API_KEY"
              />
              <Row name="YouTube upload" ok={s.publishing.youtube.configured} text={s.publishing.youtube.message ?? "ready (uploads are private)"} envs="YOUTUBE_ACCESS_TOKEN" />
            </tbody>
          </table>
        )}
        <p className="muted small">Change keys in the .env file next to the app (see .env.example), then restart the app.</p>
      </Card>
      <div className="grid grid-2">
        <Card title="Preferences">
          {draft && (
            <>
              <Field label="Default render quality">
                <select value={draft.default_quality} onChange={(e) => setDraft({ ...draft, default_quality: e.target.value as Prefs["default_quality"] })}>
                  <option value="draft">Draft (fast)</option>
                  <option value="final">Final</option>
                </select>
              </Field>
              <Field label="QA: longest allowed silence (seconds)">
                <input type="number" min={0.5} max={10} step={0.1} value={draft.max_silence_seconds} onChange={(e) => setDraft({ ...draft, max_silence_seconds: Number(e.target.value) })} />
              </Field>
              <label className="check">
                <input type="checkbox" checked={draft.use_ai} onChange={(e) => setDraft({ ...draft, use_ai: e.target.checked })} />
                Use Claude when configured (otherwise offline templates)
              </label>
              <div className="row gap" style={{ marginTop: 10 }}>
                <Button kind="primary" onClick={save} busy={action.busy === "prefs"}>
                  Save
                </Button>
                {action.notice && <span className="muted">{action.notice}</span>}
              </div>
            </>
          )}
        </Card>
        <Card title="About">
          {health.data && (
            <table>
              <tbody>
                <tr><td>Version</td><td>{health.data.version}</td></tr>
                <tr><td>Python</td><td>{health.data.python}</td></tr>
                <tr><td>Platform</td><td className="small">{health.data.platform}</td></tr>
                <tr><td>Data folder</td><td className="mono small">{health.data.data_dir}</td></tr>
                <tr><td>Exports folder</td><td className="mono small">{health.data.exports_dir}</td></tr>
                <tr><td>Logs folder</td><td className="mono small">{health.data.logs_dir}</td></tr>
                <tr><td>Database schema</td><td>v{health.data.schema_version}</td></tr>
              </tbody>
            </table>
          )}
        </Card>
      </div>
      <Card
        title="Recent log events"
        actions={
          <>
            <Button onClick={() => void logs.reload()}>Refresh</Button>
            <Button kind="ghost" onClick={() => void openLogs()}>
              Open logs folder
            </Button>
          </>
        }
      >
        <p className="muted small">Structured JSON logs; secrets are redacted before anything is written.</p>
        <div style={{ maxHeight: 360, overflow: "auto" }}>
          <table>
            <tbody>
              {logs.data?.map((l, i) => (
                <tr key={i}>
                  <td className="small muted" style={{ whiteSpace: "nowrap" }}>{l.ts}</td>
                  <td>{l.level === "ERROR" ? <Badge tone="bad">{l.level}</Badge> : l.level === "WARNING" ? <Badge tone="warn">{l.level}</Badge> : <span className="small">{l.level}</span>}</td>
                  <td className="small">{l.logger}</td>
                  <td className="small">{l.msg}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </Page>
  );
}
