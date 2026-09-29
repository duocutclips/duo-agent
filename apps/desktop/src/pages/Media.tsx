import { useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, importPicked, waitForJob } from "../api";
import { Audio, Curve, Thumb, Video } from "../components/FileMedia";
import { Badge, Button, Card, Empty, ErrorBanner, Field, JobBar, Notice, Page } from "../components/ui";
import { fmtBytes, fmtDuration, fmtTime, parseTime } from "../format";
import { useAction, useApi } from "../hooks";
import { pickFiles } from "../platform";
import type { Campaign, Job, Media, Segment } from "../types";

const VIDEO_EXT = ["mp4", "mov", "webm", "mkv", "m4v", "png", "jpg", "jpeg", "webp"];
const AUDIO_EXT = ["wav", "mp3", "ogg", "m4a", "aac", "flac"];

function SegmentRow({ seg, onChange, onSeek }: { seg: Segment; onChange: () => Promise<void>; onSeek: (t: number) => void }) {
  const [start, setStart] = useState(fmtTime(seg.start));
  const [end, setEnd] = useState(fmtTime(seg.end));
  const action = useAction();
  const save = () =>
    action.run("save", async () => {
      const s = parseTime(start);
      const e = parseTime(end);
      if (s === null || e === null) throw new Error("Use mm:ss.xx or seconds.");
      await api.patch(`/api/segments/${seg.id}`, { start: s, end: e });
      await onChange();
    });
  const toggle = () =>
    action.run("toggle", async () => {
      await api.patch(`/api/segments/${seg.id}`, { enabled: !seg.enabled });
      await onChange();
    });
  const remove = () =>
    action.run("del", async () => {
      await api.del(`/api/segments/${seg.id}`);
      await onChange();
    });
  const basis = seg.tags.find((t) => t.startsWith("basis:"))?.slice(6);
  return (
    <tr style={{ opacity: seg.enabled ? 1 : 0.5 }}>
      <td>
        <div className="row gap">
          <input value={start} onChange={(e) => setStart(e.target.value)} style={{ width: 86 }} aria-label="start" />
          –
          <input value={end} onChange={(e) => setEnd(e.target.value)} style={{ width: 86 }} aria-label="end" />
          {(start !== fmtTime(seg.start) || end !== fmtTime(seg.end)) && (
            <Button onClick={save} busy={action.busy === "save"}>
              Save
            </Button>
          )}
        </div>
        {action.error && <div className="qa-fail small">{action.error.message}</div>}
      </td>
      <td>
        {seg.label}
        <div className="muted small">{basis}</div>
        <div className="row gap">
          {seg.tags
            .filter((t) => !t.startsWith("basis:"))
            .map((t) => (
              <Badge key={t} tone={t === "hook_candidate" ? "accent" : t === "repeated" ? "warn" : "neutral"}>
                {t}
              </Badge>
            ))}
          <Badge>{seg.source}</Badge>
        </div>
      </td>
      <td>{seg.score.toFixed(2)}</td>
      <td>{seg.confidence.toFixed(2)}</td>
      <td>
        <div className="row gap">
          <Button kind="ghost" onClick={() => onSeek(seg.start)}>
            ▶
          </Button>
          <Button kind="ghost" onClick={toggle}>
            {seg.enabled ? "Disable" : "Enable"}
          </Button>
          <Button kind="ghost" onClick={remove}>
            ✕
          </Button>
        </div>
      </td>
    </tr>
  );
}

function VideoDetail({ m, reload }: { m: Media; reload: () => Promise<void> }) {
  const segs = useApi<Segment[]>(`/api/media/${m.id}/segments`);
  const action = useAction();
  const [job, setJob] = useState<Job | null>(null);
  const [ns, setNs] = useState("");
  const [ne, setNe] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);
  const analyze = () =>
    action.run("analyze", async () => {
      const j = await api.post<Job>(`/api/media/${m.id}/analyze`);
      await waitForJob(j.id, setJob);
      setJob(null);
      await Promise.all([segs.reload(), reload()]);
    });
  const add = () =>
    action.run("add", async () => {
      const s = parseTime(ns);
      const e = parseTime(ne);
      if (s === null || e === null) throw new Error("Use mm:ss.xx or seconds.");
      await api.post(`/api/media/${m.id}/segments`, { start: s, end: e });
      setNs("");
      setNe("");
      await segs.reload();
    });
  const seek = (t: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = t;
      void videoRef.current.play();
    }
  };
  const a = m.analysis;
  return (
    <div className="grid grid-2" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,2fr)", marginTop: 12 }}>
      <div>
        <Video ref={videoRef} path={`/api/files/media/${m.id}`} className="preview-video" />
      </div>
      <div>
        <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
        <JobBar job={job} />
        <div className="row gap" style={{ marginBottom: 10 }}>
          <Button kind="primary" onClick={analyze} busy={action.busy === "analyze"}>
            {a ? "Re-analyse" : "Analyse gameplay"}
          </Button>
          <span className="muted small">Signals only: motion, scene changes, loudness, silence, black/static and repeated frames. No object recognition.</span>
        </div>
        {a && (
          <>
            <div className="tl-label">Motion (2 samples/s)</div>
            <Curve values={a.motion_curve} color="#9d86ff" />
            <div className="tl-label">Audio loudness dB</div>
            <Curve values={a.audio_curve} color="#4db7ff" min={-70} max={0} />
            <p className="small muted">
              Scene changes: {a.cuts.map((c) => fmtTime(c)).join(", ") || "none"} · Silence: {a.silence.map(([s, e]) => `${fmtTime(s)}–${fmtTime(e)}`).join(", ") || "none"} · Black:{" "}
              {a.black.map(([s, e]) => `${fmtTime(s)}–${fmtTime(e)}`).join(", ") || "none"} · Static: {a.static.map(([s, e]) => `${fmtTime(s)}–${fmtTime(e)}`).join(", ") || "none"} · Repeated:{" "}
              {a.repeats.map((r) => `${fmtTime(r.repeat_start)}–${fmtTime(r.repeat_end)} (of ${fmtTime(r.first_start)})`).join(", ") || "none"}
            </p>
          </>
        )}
        {segs.data && segs.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Candidate</th>
                <th>Score</th>
                <th>Conf.</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {segs.data.map((s) => (
                <SegmentRow key={s.id + s.start + s.end + s.enabled} seg={s} onChange={segs.reload} onSeek={seek} />
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No segments yet.</Empty>
        )}
        <div className="row gap" style={{ marginTop: 10 }}>
          <input value={ns} onChange={(e) => setNs(e.target.value)} placeholder="start (mm:ss)" style={{ width: 120 }} />
          <input value={ne} onChange={(e) => setNe(e.target.value)} placeholder="end (mm:ss)" style={{ width: 120 }} />
          <Button onClick={add} disabled={!ns || !ne} busy={action.busy === "add"}>
            Add manual segment
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function MediaPage() {
  const [params] = useSearchParams();
  const campaignFilter = params.get("campaign") ?? "";
  const [tab, setTab] = useState<"video" | "sfx" | "music">("video");
  const [campaignId, setCampaignId] = useState(campaignFilter);
  const campaigns = useApi<Campaign[]>("/api/campaigns");
  const cats = useApi<string[]>("/api/media/sfx-categories");
  const list = useApi<Media[]>(`/api/media${tab === "video" ? "" : `?kind=${tab}`}`);
  const [open, setOpen] = useState<string | null>(null);
  const [category, setCategory] = useState("impact");
  const [license, setLicense] = useState("");
  const action = useAction();

  const rows = (list.data ?? []).filter((m) => (tab === "video" ? m.kind === "video" || m.kind === "image" : true)).filter((m) => !campaignId || tab !== "video" || m.campaign_id === campaignId);

  const importFiles = () =>
    action.run("import", async () => {
      const exts = tab === "video" ? VIDEO_EXT : tab === "sfx" ? ["wav", "mp3", "ogg"] : AUDIO_EXT;
      const picked = await pickFiles(exts);
      let dup = 0;
      for (const p of picked) {
        const r = await importPicked<Media>(p, {
          kind: tab === "video" ? undefined : tab,
          campaign_id: tab === "video" ? campaignId || undefined : undefined,
          category: tab === "sfx" ? category : undefined,
          license_note: tab === "music" ? license : tab === "sfx" ? license || "User-imported" : undefined,
        });
        if (r.deduplicated) dup++;
      }
      await list.reload();
      if (dup) action.setNotice(`${dup} file(s) were already in the library and were not duplicated.`);
    });
  const remove = (m: Media) =>
    action.run("del:" + m.id, async () => {
      if (!window.confirm(`Remove ${m.filename} from the library? Your original file is not deleted.`)) return;
      await api.del(`/api/media/${m.id}`);
      await list.reload();
    });
  const setCat = (m: Media, c: string) =>
    action.run("cat", async () => {
      await api.patch(`/api/media/${m.id}`, { category: c });
      await list.reload();
    });

  return (
    <Page title="Media" subtitle="Local library. Files imported in the desktop app are referenced in place (not copied); identical files are never duplicated.">
      <div className="tabs">
        {(
          [
            ["video", "Gameplay footage & images"],
            ["sfx", "Sound effects"],
            ["music", "Music"],
          ] as const
        ).map(([k, l]) => (
          <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>
            {l}
          </button>
        ))}
      </div>
      <ErrorBanner error={action.error ?? list.error} onClose={() => action.setError(null)} />
      {action.notice && <Notice>{action.notice}</Notice>}
      <Card>
        <div className="row gap">
          {tab === "video" && (
            <Field label="Campaign">
              <select value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
                <option value="">All / unassigned</option>
                {campaigns.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {tab === "sfx" && (
            <Field label="Category for new sound effects">
              <select value={category} onChange={(e) => setCategory(e.target.value)}>
                {cats.data?.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </Field>
          )}
          {tab === "music" && (
            <Field label="License / authorisation note (required)" hint="Only import music that is royalty-cleared or that you are authorised to use.">
              <input value={license} onChange={(e) => setLicense(e.target.value)} placeholder="e.g. Epidemic Sound licence #1234" style={{ minWidth: 320 }} />
            </Field>
          )}
          <Button kind="primary" onClick={importFiles} busy={action.busy === "import"} disabled={tab === "music" && !license.trim()}>
            Import {tab === "video" ? "footage" : tab === "sfx" ? "sound effects" : "music"}…
          </Button>
        </div>
      </Card>
      {rows.length === 0 ? (
        <Empty>Nothing here yet.</Empty>
      ) : (
        rows.map((m) => (
          <Card key={m.id}>
            <div className="row gap-lg spread">
              <div className="row gap-lg">
                <Thumb path={m.thumbnail ? `/api/files/thumb/${m.id}` : null} />
                <div>
                  <strong>{m.filename}</strong> {m.missing && <Badge tone="bad">file missing</Badge>}
                  <div className="muted small">
                    {m.kind === "video" &&
                      `${m.width}×${m.height} · ${m.fps ?? "?"} fps · ${m.orientation} · ${m.codec}${m.has_audio ? ` + ${m.audio_codec}` : " · no audio"} · `}
                    {m.kind !== "video" && m.kind !== "image" && `${m.audio_codec} · `}
                    {fmtDuration(m.duration)} · {fmtBytes(m.size)}
                  </div>
                  <div className="muted small mono">{m.path}</div>
                  {m.license_note && <div className="small">License: {m.license_note}</div>}
                  {m.kind === "video" && (
                    <div className="small">{m.analysis ? <Badge tone="good">analysed · {m.segment_count} segments</Badge> : <Badge tone="warn">not analysed</Badge>}</div>
                  )}
                </div>
              </div>
              <div className="row gap">
                {m.kind === "sfx" && (
                  <select value={m.category ?? ""} onChange={(e) => setCat(m, e.target.value)} style={{ width: 150 }}>
                    {cats.data?.map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                )}
                {m.kind === "video" && <Button onClick={() => setOpen(open === m.id ? null : m.id)}>{open === m.id ? "Close" : "Analyse / segments"}</Button>}
                <Button kind="danger" onClick={() => remove(m)}>
                  Remove
                </Button>
              </div>
            </div>
            {(m.kind === "sfx" || m.kind === "music") && (
              <div style={{ marginTop: 8 }}>
                <Audio path={`/api/files/media/${m.id}`} />
              </div>
            )}
            {open === m.id && <VideoDetail m={m} reload={list.reload} />}
          </Card>
        ))
      )}
    </Page>
  );
}
