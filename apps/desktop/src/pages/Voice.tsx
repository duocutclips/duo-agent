import { useState } from "react";
import { api } from "../api";
import { Badge, Button, Card, ErrorBanner, Field, Notice, Page } from "../components/ui";
import { useAction, useApi } from "../hooks";
import type { IntegrationStatus, VoiceProfile } from "../types";

interface CatalogVoice {
  voice_id: string;
  name: string;
  category: string;
}

function ProfileCard({ v, reload }: { v: VoiceProfile; reload: () => Promise<void> }) {
  const [settings, setSettings] = useState(v.settings);
  const [authorized, setAuthorized] = useState(v.authorized);
  const action = useAction();
  const save = () =>
    action.run("save", async () => {
      await api.patch(`/api/voices/${v.id}`, { settings, authorized });
      await reload();
    }, "Saved.");
  const remove = () =>
    action.run("del", async () => {
      await api.del(`/api/voices/${v.id}`);
      await reload();
    });
  const num = (k: string, label: string, min: number, max: number, step: number) => (
    <Field label={`${label}: ${Number(settings[k] ?? 0).toFixed(2)}`}>
      <input type="range" min={min} max={max} step={step} value={Number(settings[k] ?? 0)} onChange={(e) => setSettings({ ...settings, [k]: Number(e.target.value) })} />
    </Field>
  );
  return (
    <Card
      title={
        <>
          {v.name} <Badge tone={v.provider === "elevenlabs" ? "accent" : "neutral"}>{v.provider}</Badge>
        </>
      }
      actions={
        <Button kind="ghost" onClick={remove}>
          Delete
        </Button>
      }
    >
      <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
      {v.voice_id && <p className="small mono">voice id: {v.voice_id}</p>}
      <div className="grid grid-3">
        {num("speed", "Speed", 0.7, 1.2, 0.01)}
        {v.provider === "elevenlabs" && num("stability", "Stability", 0, 1, 0.01)}
        {v.provider === "elevenlabs" && num("similarity_boost", "Similarity", 0, 1, 0.01)}
        {v.provider === "elevenlabs" && num("style", "Style", 0, 1, 0.01)}
        {v.provider === "elevenlabs" && (
          <Field label="Output format">
            <select value={String(settings.output_format ?? "mp3_44100_128")} onChange={(e) => setSettings({ ...settings, output_format: e.target.value })}>
              {["mp3_44100_128", "mp3_44100_192", "pcm_44100", "mp3_22050_32"].map((f) => (
                <option key={f}>{f}</option>
              ))}
            </select>
          </Field>
        )}
      </div>
      <label className="check">
        <input type="checkbox" checked={authorized} onChange={(e) => setAuthorized(e.target.checked)} />I own this voice or have permission to use it for this content.
      </label>
      <div className="row gap" style={{ marginTop: 10 }}>
        <Button kind="primary" onClick={save} busy={action.busy === "save"}>
          Save
        </Button>
        {action.notice && <span className="muted">{action.notice}</span>}
      </div>
    </Card>
  );
}

export default function VoicePage() {
  const voices = useApi<VoiceProfile[]>("/api/voices");
  const status = useApi<IntegrationStatus>("/api/status");
  const [catalog, setCatalog] = useState<CatalogVoice[] | null>(null);
  const [name, setName] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const action = useAction();
  const eleven = status.data?.voice.elevenlabs;
  const sys = status.data?.voice.system;

  const loadCatalog = () => action.run("catalog", async () => setCatalog(await api.get<CatalogVoice[]>("/api/voices/elevenlabs/catalog")));
  const add = () =>
    action.run("add", async () => {
      await api.post("/api/voices", { provider: "elevenlabs", name: name || "ElevenLabs voice", voice_id: voiceId, authorized });
      setName("");
      setVoiceId("");
      setAuthorized(false);
      await voices.reload();
    });
  const addSystem = () =>
    action.run("sys", async () => {
      await api.post("/api/voices", { provider: "system", name: "Offline draft voice" });
      await voices.reload();
    });

  return (
    <Page title="Voice" subtitle="Narration is cached: identical text + voice + settings is never regenerated.">
      <ErrorBanner error={action.error ?? voices.error} onClose={() => action.setError(null)} />
      <div className="grid grid-2">
        <Card title="ElevenLabs">
          {eleven?.configured ? <Badge tone="good">configured</Badge> : <Notice tone="warn">{eleven?.message ?? "Checking…"}</Notice>}
          <Field label="Profile name">
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Voice ID">
            <div className="row gap">
              <input value={voiceId} onChange={(e) => setVoiceId(e.target.value)} style={{ flex: 1, width: "auto" }} />
              <Button onClick={loadCatalog} disabled={!eleven?.configured} busy={action.busy === "catalog"}>
                Browse my voices
              </Button>
            </div>
          </Field>
          {catalog && (
            <select onChange={(e) => setVoiceId(e.target.value)} value={voiceId}>
              <option value="">Pick a voice…</option>
              {catalog.map((c) => (
                <option key={c.voice_id} value={c.voice_id}>
                  {c.name} ({c.category})
                </option>
              ))}
            </select>
          )}
          <label className="check" style={{ margin: "10px 0" }}>
            <input type="checkbox" checked={authorized} onChange={(e) => setAuthorized(e.target.checked)} />I own this voice or have permission to use it (required for cloned voices).
          </label>
          <Button kind="primary" onClick={add} disabled={!voiceId} busy={action.busy === "add"}>
            Add ElevenLabs voice
          </Button>
        </Card>
        <Card title="Offline system voice">
          {sys?.available ? <Badge tone="good">{sys.engine} available</Badge> : <Notice tone="warn">{sys?.message ?? "Checking…"}</Notice>}
          <p className="muted">Robotic but free and offline. Use it for drafts and timing tests; switch to ElevenLabs for final narration.</p>
          <Button onClick={addSystem} busy={action.busy === "sys"}>
            Add offline voice profile
          </Button>
        </Card>
      </div>
      {voices.data?.map((v) => <ProfileCard key={v.id} v={v} reload={voices.reload} />)}
    </Page>
  );
}
