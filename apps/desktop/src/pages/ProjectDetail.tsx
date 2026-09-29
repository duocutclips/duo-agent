import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, waitForJob } from "../api";
import { Audio, Video } from "../components/FileMedia";
import ScriptEditor from "../components/ScriptEditor";
import TimelineView, { retimeCaption } from "../components/TimelineView";
import { Badge, Button, Card, Empty, ErrorBanner, Field, JobBar, Notice, Page, StageStepper, StatusBadge } from "../components/ui";
import { fmtDate, fmtDuration, fmtTime } from "../format";
import { useAction, useApi, useDefaultQuality } from "../hooks";
import { copyText, openExternal } from "../platform";
import type { IntegrationStatus, Job, Media, Project, PublishKit, Script, Template, Timeline, TimelineItem, VoiceProfile } from "../types";

type Tab = "script" | "voice" | "footage" | "timeline" | "review" | "publish" | "history";
const TABS: [Tab, string][] = [
  ["script", "Script"],
  ["voice", "Voice"],
  ["footage", "Footage & style"],
  ["timeline", "Timeline"],
  ["review", "Preview & QA"],
  ["publish", "Export & publish"],
  ["history", "History"],
];

type Ctx = {
  p: Project;
  setP: (p: Project) => void;
  reload: () => Promise<void>;
  action: ReturnType<typeof useAction>;
  runJob: (label: string, path: string, body: unknown) => Promise<void>;
};

const locked = (p: Project) => ["EXPORTED", "POSTED", "SUBMITTED"].includes(p.status);

function ScriptTab({ p, setP, action }: Ctx) {
  const [target, setTarget] = useState<number | "">("");
  const scripts = useApi<Script[]>(`/api/scripts?campaign_id=${p.campaign_id}`);
  const forIdea = (scripts.data ?? []).filter((s) => s.idea_id === p.idea_id);
  const generate = () =>
    action.run("script", async () => setP(await api.post<Project>(`/api/projects/${p.id}/script`, { target_seconds: target || null })));
  const choose = (sid: string) => action.run("pick", async () => setP(await api.put<Project>(`/api/projects/${p.id}/script`, { script_id: sid })));
  return (
    <>
      {p.idea && (
        <Card title="Idea">
          <strong>{p.idea.title}</strong>
          <p>
            <span className="muted">Hook:</span> {p.idea.hook}
          </p>
          <p className="muted small">{p.idea.concept}</p>
        </Card>
      )}
      <Card title="Script">
        <div className="row gap">
          <Field label="Target">
            <select value={target} onChange={(e) => setTarget(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Auto (fits campaign length)</option>
              {[15, 20, 30, 45].map((t) => (
                <option key={t} value={t}>
                  {t} sec
                </option>
              ))}
            </select>
          </Field>
          <Button kind={p.script ? "default" : "primary"} onClick={generate} busy={action.busy === "script"} disabled={!p.idea_id}>
            {p.script ? "Regenerate script" : "Generate script"}
          </Button>
          {forIdea.length > 1 && (
            <Field label="Or use an earlier script">
              <select value={p.script_id ?? ""} onChange={(e) => void choose(e.target.value)}>
                {forIdea.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.target_seconds}s · {fmtDate(s.updated_at)} · {s.text.slice(0, 40)}…
                  </option>
                ))}
              </select>
            </Field>
          )}
        </div>
        {p.script ? (
          <ScriptEditor
            script={p.script}
            onSaved={async () => {
              // Editing the script invalidates narration and everything after it.
              setP(await api.put<Project>(`/api/projects/${p.id}/script`, { script_id: p.script_id }));
            }}
          />
        ) : (
          <Empty>No script yet.</Empty>
        )}
      </Card>
    </>
  );
}

function VoiceTab({ p, setP, action }: Ctx) {
  const voices = useApi<VoiceProfile[]>("/api/voices");
  const [voiceId, setVoiceId] = useState("");
  const generate = () =>
    action.run("voice", async () => setP(await api.post<Project>(`/api/projects/${p.id}/voice`, { voice_profile_id: voiceId || null })));
  const n = p.narration;
  return (
    <Card title="Narration">
      {!p.script && <Notice tone="warn">Generate or write a script first.</Notice>}
      <div className="row gap">
        <Field label="Voice">
          <select value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
            <option value="">Default (first authorized voice)</option>
            {voices.data?.map((v) => (
              <option key={v.id} value={v.id} disabled={!v.authorized}>
                {v.name} ({v.provider}){v.authorized ? "" : " — not authorized"}
              </option>
            ))}
          </select>
        </Field>
        <Button kind={n ? "default" : "primary"} onClick={generate} busy={action.busy === "voice"} disabled={!p.script}>
          {n ? "Regenerate narration" : "Generate narration"}
        </Button>
        <Link to="/voice">Manage voices</Link>
      </div>
      {n ? (
        <div style={{ marginTop: 12 }}>
          <div className="row gap">
            <Badge tone="info">{n.provider}</Badge>
            <Badge>{fmtDuration(n.duration)}</Badge>
            <Badge tone={n.alignment_method.includes("estimated") ? "warn" : "good"} title="How word timings for captions were obtained">
              timing: {n.alignment_method}
            </Badge>
          </div>
          <Audio path={`/api/files/narration/${n.id}`} bust={n.id} />
          {n.alignment_method.includes("estimated") && (
            <p className="muted small">
              Word timings are estimated from syllables and detected pauses (no speech-to-text configured). Captions will be close but not exact.
            </p>
          )}
          <p className="small">
            {n.words.slice(0, 60).map((w, i) => (
              <span key={i} title={`${fmtTime(w.start)}–${fmtTime(w.end)}`}>
                {w.word}{" "}
              </span>
            ))}
            {n.words.length > 60 && "…"}
          </p>
        </div>
      ) : (
        <Empty>No narration yet.</Empty>
      )}
    </Card>
  );
}

function FootageTab({ p, setP, action }: Ctx) {
  const media = useApi<Media[]>("/api/media");
  const templates = useApi<Template[]>("/api/templates");
  const [mediaIds, setMediaIds] = useState(p.media_ids);
  const [musicId, setMusicId] = useState(p.music_id ?? "");
  const [templateId, setTemplateId] = useState(p.template_id);
  const [seed, setSeed] = useState(p.seed);
  useEffect(() => {
    setMediaIds(p.media_ids);
    setMusicId(p.music_id ?? "");
    setTemplateId(p.template_id);
    setSeed(p.seed);
  }, [p.media_ids, p.music_id, p.template_id, p.seed]);
  const videos = (media.data ?? []).filter((m) => m.kind === "video" && (!m.campaign_id || m.campaign_id === p.campaign_id));
  const music = (media.data ?? []).filter((m) => m.kind === "music" && (!m.campaign_id || m.campaign_id === p.campaign_id));
  const dirty = JSON.stringify(mediaIds) !== JSON.stringify(p.media_ids) || musicId !== (p.music_id ?? "") || templateId !== p.template_id || seed !== p.seed;
  const save = () =>
    action.run(
      "footage",
      async () => setP(await api.patch<Project>(`/api/projects/${p.id}`, { media_ids: mediaIds, music_id: musicId || null, template_id: templateId, seed })),
      "Saved. The timeline will be rebuilt with these inputs.",
    );
  return (
    <Card title="Footage, music and template">
      {locked(p) && <Notice tone="warn">This video was exported. Duplicate the project to change its inputs.</Notice>}
      <div className="field-label">Gameplay clips to draw segments from</div>
      {videos.length === 0 && (
        <Empty>
          No videos for this campaign. <Link to="/media">Import gameplay</Link> first.
        </Empty>
      )}
      <ul className="item-list">
        {videos.map((m) => (
          <li key={m.id}>
            <label className="check">
              <input
                type="checkbox"
                checked={mediaIds.includes(m.id)}
                onChange={(e) => setMediaIds(e.target.checked ? [...mediaIds, m.id] : mediaIds.filter((x) => x !== m.id))}
              />
              {m.filename} <span className="muted small">· {fmtDuration(m.duration)} · {m.segment_count ?? 0} segments</span>
              {!m.analysis && <Badge tone="warn">not analyzed</Badge>}
            </label>
          </li>
        ))}
      </ul>
      <div className="grid grid-3" style={{ marginTop: 10 }}>
        <Field label="Template">
          <select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
            {templates.data?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Music">
          <select value={musicId} onChange={(e) => setMusicId(e.target.value)}>
            <option value="">None</option>
            {music.map((m) => (
              <option key={m.id} value={m.id}>
                {m.filename}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Variation seed" hint="Changes which segments, zooms and SFX are picked.">
          <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
        </Field>
      </div>
      <Button kind="primary" onClick={save} disabled={!dirty || locked(p)} busy={action.busy === "footage"}>
        Save
      </Button>
      {action.notice && <span className="muted"> {action.notice}</span>}
    </Card>
  );
}

function TimelineTab({ p, setP, action }: Ctx) {
  const [draft, setDraft] = useState<Timeline | null>(p.timeline);
  const [raw, setRaw] = useState<string | null>(null);
  useEffect(() => setDraft(p.timeline), [p.timeline]);
  const build = () => action.run("tl", async () => setP(await api.post<Project>(`/api/projects/${p.id}/timeline`)));
  const save = (tl: Timeline) =>
    action.run("save-tl", async () => {
      setP(await api.put<Project>(`/api/projects/${p.id}/timeline`, tl));
      setRaw(null);
    }, "Timeline saved. Render again to see the change.");

  if (!draft)
    return (
      <Card title="Timeline">
        <p className="muted">The editor picks segments that match the narration, adds cuts on sentence boundaries, zooms, captions, SFX and music.</p>
        <Button kind="primary" onClick={build} busy={action.busy === "tl"} disabled={!p.narration}>
          Build timeline
        </Button>
        {!p.narration && <Notice tone="warn">Generate the narration first.</Notice>}
      </Card>
    );

  const items = draft.items;
  const videoIdx = items.map((it, i) => [it, i] as const).filter(([it]) => it.type === "video");
  const textIdx = items.map((it, i) => [it, i] as const).filter(([it]) => it.type === "caption" || it.type === "text");
  const setItem = (i: number, it: TimelineItem) => setDraft({ ...draft, items: items.map((x, j) => (j === i ? it : x)) });
  const setBoundary = (k: number, t: number) => {
    // Move the cut between clip k and clip k+1, keeping clips contiguous.
    const [a, ai] = videoIdx[k];
    const [b, bi] = videoIdx[k + 1];
    const next = items.slice();
    next[ai] = { ...a, end: t };
    next[bi] = { ...b, start: t };
    setDraft({ ...draft, items: next });
  };
  const dirty = JSON.stringify(draft) !== JSON.stringify(p.timeline);

  return (
    <>
      <Card
        title={`Timeline · ${fmtDuration(draft.duration)} · ${videoIdx.length} clips`}
        actions={
          <>
            <Button onClick={build} busy={action.busy === "tl"} disabled={locked(p)} title="Rebuild from narration, footage and template">
              Rebuild
            </Button>
            <Button onClick={() => setRaw(JSON.stringify(draft, null, 2))}>Edit JSON</Button>
            <Button kind="primary" onClick={() => void save(draft)} disabled={!dirty || locked(p)} busy={action.busy === "save-tl"}>
              Save edits
            </Button>
          </>
        }
      >
        {action.notice && <Notice tone="good">{action.notice}</Notice>}
        {draft.warnings?.map((w) => (
          <Notice key={w} tone="warn">
            {w}
          </Notice>
        ))}
        <TimelineView timeline={draft} />
      </Card>
      {raw !== null && (
        <Card title="Timeline JSON" actions={<Button kind="ghost" onClick={() => setRaw(null)}>Close</Button>}>
          <p className="muted small">Validated against the timeline schema on save. Clips must stay contiguous.</p>
          <textarea className="mono" value={raw} onChange={(e) => setRaw(e.target.value)} style={{ minHeight: 360 }} aria-label="timeline json" />
          <Button
            kind="primary"
            onClick={() => {
              try {
                void save(JSON.parse(raw) as Timeline);
              } catch (e) {
                action.setError({ code: "json", message: "That is not valid JSON.", detail: String(e) });
              }
            }}
          >
            Save JSON
          </Button>
        </Card>
      )}
      <Card title="Clips">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Source</th>
              <th>Start</th>
              <th>End (cut)</th>
              <th>Source in</th>
              <th>Label</th>
            </tr>
          </thead>
          <tbody>
            {videoIdx.map(([it, i], k) => (
              <tr key={i}>
                <td>{k + 1}</td>
                <td className="small">{String(it.source).split(/[\\/]/).pop()}</td>
                <td>{fmtTime(it.start)}</td>
                <td>
                  {k < videoIdx.length - 1 ? (
                    <input type="number" step="0.05" value={it.end} onChange={(e) => setBoundary(k, Number(e.target.value))} style={{ width: 90 }} aria-label={`cut ${k + 1}`} />
                  ) : (
                    fmtTime(it.end)
                  )}
                </td>
                <td>
                  <input type="number" step="0.1" min={0} value={Number(it.src_in ?? 0)} onChange={(e) => setItem(i, { ...it, src_in: Number(e.target.value) })} style={{ width: 90 }} />
                </td>
                <td className="small muted">{String(it.label ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title="Captions and on-screen text">
        <p className="muted small">Edit wording here; word timings are kept when the word count matches, otherwise spread evenly over the caption.</p>
        <table>
          <tbody>
            {textIdx.map(([it, i]) => (
              <tr key={i}>
                <td className="small muted" style={{ width: 120 }}>
                  {it.type === "text" ? String(it.role ?? "text") : "caption"} {fmtTime(it.start)}
                </td>
                <td>
                  <input value={String(it.text ?? "")} onChange={(e) => setItem(i, it.type === "caption" ? retimeCaption(it, e.target.value) : { ...it, text: e.target.value })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}

function ReviewTab({ p, setP, action, runJob }: Ctx) {
  const video = useRef<HTMLVideoElement>(null);
  const [quality, setQuality] = useDefaultQuality();
  const [note, setNote] = useState("");
  const qa = () => action.run("qa", async () => setP(await api.post<Project>(`/api/projects/${p.id}/qa`)));
  const status = (s: string) =>
    action.run("status-" + s, async () => {
      setP(await api.post<Project>(`/api/projects/${p.id}/status`, { status: s, note }));
      setNote("");
    });
  return (
    <div className="grid grid-2">
      <Card
        title="Preview"
        actions={
          <>
            <select value={quality} onChange={(e) => setQuality(e.target.value as "draft" | "final")} aria-label="quality">
              <option value="draft">Draft (fast)</option>
              <option value="final">Final quality</option>
            </select>
            <Button kind="primary" onClick={() => void runJob("render", `/api/projects/${p.id}/render`, { quality })} busy={action.busy === "render"} disabled={!p.timeline}>
              Render
            </Button>
          </>
        }
      >
        {!p.timeline && <Notice tone="warn">Build the timeline first.</Notice>}
        {p.render_path ? <Video ref={video} path={`/api/files/render/${p.id}`} bust={p.render_path} /> : <Empty>Not rendered yet.</Empty>}
        {p.timeline && p.render_path && (
          <TimelineView
            timeline={p.timeline}
            onSeek={(t) => {
              if (video.current) video.current.currentTime = t;
            }}
          />
        )}
      </Card>
      <div>
        <Card
          title={
            <>
              Quality check {p.qa && <Badge tone={p.ready ? "good" : "bad"}>{p.qa.overall}</Badge>}
            </>
          }
          actions={
            <Button onClick={qa} busy={action.busy === "qa"} disabled={!p.render_path}>
              {p.qa ? "Re-run QA" : "Run QA"}
            </Button>
          }
        >
          {p.qa ? (
            <table>
              <tbody>
                {p.qa.checks.map((c) => (
                  <tr key={c.name}>
                    <td className={c.status === "PASS" ? "qa-pass" : c.status === "FAIL" ? "qa-fail" : "qa-na"} style={{ width: 50 }}>
                      {c.status}
                    </td>
                    <td>{c.name}</td>
                    <td className="small muted">{c.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>Render, then run QA. QA runs automatically after a pipeline render.</Empty>
          )}
        </Card>
        <Card
          title={
            <>
              Approval <StatusBadge status={p.status} />
            </>
          }
        >
          <p className="muted small">Nothing is exported or posted without your approval. QA must be READY before review.</p>
          <Field label="Note (required to reject)">
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What should change?" />
          </Field>
          <div className="row gap">
            {p.status === "DRAFT" && (
              <Button kind="primary" onClick={() => void status("REVIEW")} disabled={!p.ready} busy={action.busy === "status-REVIEW"}>
                Send to review
              </Button>
            )}
            {p.status === "REVIEW" && (
              <>
                <Button kind="primary" onClick={() => void status("APPROVED")} busy={action.busy === "status-APPROVED"}>
                  Approve
                </Button>
                <Button kind="danger" onClick={() => void status("REJECTED")} disabled={!note.trim()} busy={action.busy === "status-REJECTED"}>
                  Reject
                </Button>
              </>
            )}
            {["REVIEW", "REJECTED", "APPROVED", "EXPORTED"].includes(p.status) && (
              <Button onClick={() => void status("DRAFT")} busy={action.busy === "status-DRAFT"} title="Back to draft to edit and regenerate">
                Back to draft
              </Button>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

function PublishTab({ p, setP, action, reload }: Ctx) {
  const kit = useApi<PublishKit>(`/api/projects/${p.id}/publish-kit`);
  const status = useApi<IntegrationStatus>("/api/status");
  const [caption, setCaption] = useState(p.caption_text);
  const [tags, setTags] = useState(p.hashtags.join(" "));
  const [platform, setPlatform] = useState("");
  const [url, setUrl] = useState("");
  const [confirmYt, setConfirmYt] = useState(false);
  useEffect(() => {
    setCaption(p.caption_text);
    setTags(p.hashtags.join(" "));
  }, [p.caption_text, p.hashtags]);
  const saveText = () =>
    action.run("text", async () => {
      setP(await api.patch<Project>(`/api/projects/${p.id}`, { caption_text: caption, hashtags: tags.split(/\s+/).filter(Boolean) }));
      await kit.reload();
    }, "Caption saved.");
  const exp = () =>
    action.run("export", async () => {
      setP(await api.post<Project>(`/api/projects/${p.id}/export`));
      await kit.reload();
    });
  const openFile = (path: string) => action.run("open", () => api.post(`/api/system/open`, { path }));
  const markPosted = () =>
    action.run("posted", async () => {
      await api.post(`/api/projects/${p.id}/mark-posted`, { platform, post_url: url });
      setUrl("");
      await reload();
    }, "Recorded. Track views and earnings in Submissions.");
  const youtube = () =>
    action.run("yt", async () => {
      await api.post(`/api/projects/${p.id}/publish`, { provider: "youtube", confirm: true });
      await reload();
    }, "Uploaded to YouTube as a private video. Review it in YouTube Studio before making it public.");
  const exported = !!p.export_path;
  const platforms = kit.data?.platforms ?? [];
  const yt = status.data?.publishing.youtube;

  return (
    <div className="grid grid-2">
      <Card title="Caption and hashtags">
        <Field label="Caption">
          <textarea value={caption} onChange={(e) => setCaption(e.target.value)} style={{ minHeight: 90 }} />
        </Field>
        <Field label="Hashtags (space separated)">
          <input value={tags} onChange={(e) => setTags(e.target.value)} />
        </Field>
        <div className="row gap">
          <Button onClick={saveText} busy={action.busy === "text"} disabled={caption === p.caption_text && tags === p.hashtags.join(" ")}>
            Save
          </Button>
          <Button kind="ghost" onClick={() => void copyText(caption)}>
            Copy caption
          </Button>
          <Button kind="ghost" onClick={() => void copyText(tags)}>
            Copy hashtags
          </Button>
        </div>
      </Card>
      <Card title="Export">
        {exported ? (
          <>
            <p className="mono small">{p.export_path}</p>
            <div className="row gap">
              <Button onClick={() => void openFile(p.export_path!)}>Open file</Button>
              <Button kind="ghost" onClick={() => void openFile(p.export_path!.replace(/[\\/][^\\/]+$/, ""))}>
                Open folder
              </Button>
            </div>
          </>
        ) : (
          <>
            <p className="muted">Exports go to exports/&lt;campaign&gt;/concept-NN.mp4 and never overwrite an existing file.</p>
            <Button kind="primary" onClick={exp} disabled={p.status !== "APPROVED"} busy={action.busy === "export"}>
              Export video
            </Button>
            {p.status !== "APPROVED" && <p className="muted small">Approve the video first (Preview &amp; QA tab).</p>}
          </>
        )}
      </Card>
      <Card title="Post manually (recommended)">
        <p className="muted small">Open the platform, upload the exported file, paste the caption, then record the post link here.</p>
        <div className="row gap" style={{ flexWrap: "wrap", marginBottom: 10 }}>
          {platforms.map((pl) => (
            <Button key={pl.name} kind="ghost" onClick={() => openExternal(pl.url)} disabled={!pl.url}>
              Open {pl.name}
            </Button>
          ))}
        </div>
        <div className="row gap">
          <select value={platform} onChange={(e) => setPlatform(e.target.value)} aria-label="platform">
            <option value="">Platform…</option>
            {platforms.map((pl) => (
              <option key={pl.name}>{pl.name}</option>
            ))}
          </select>
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://… post link" style={{ flex: 1, width: "auto" }} />
          <Button kind="primary" onClick={markPosted} disabled={!exported || !platform || !url} busy={action.busy === "posted"}>
            Mark posted
          </Button>
        </div>
      </Card>
      <Card title="YouTube upload (official API)">
        {yt?.configured ? (
          <>
            <p className="muted small">Uploads through the YouTube Data API as a private video. Nothing is published publicly by the app.</p>
            <label className="check">
              <input type="checkbox" checked={confirmYt} onChange={(e) => setConfirmYt(e.target.checked)} />I reviewed this video and want to upload it to my channel.
            </label>
            <Button onClick={youtube} disabled={!exported || !confirmYt || p.status !== "EXPORTED"} busy={action.busy === "yt"}>
              Upload privately
            </Button>
          </>
        ) : (
          <Notice tone="warn">{yt?.message ?? "Not configured."}</Notice>
        )}
      </Card>
    </div>
  );
}

function HistoryTab({ p }: Ctx) {
  return (
    <Card title="History">
      <ul className="item-list">
        {[...p.history].reverse().map((h, i) => (
          <li key={i}>
            <span className="small muted">{fmtDate(h.at)}</span> {h.event}
            {h.note && <span className="muted"> · {h.note}</span>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function ProjectDetail() {
  const { id = "" } = useParams();
  const { data: p, error, reload, setData } = useApi<Project>(`/api/projects/${id}`);
  const [tab, setTab] = useState<Tab>("review");
  const [job, setJob] = useState<Job | null>(null);
  const [quality, setQuality] = useDefaultQuality();
  const [title, setTitle] = useState<string | null>(null);
  const action = useAction();
  const nav = useNavigate();

  // Resume watching a render/pipeline job that is still running (e.g. after navigating away).
  useEffect(() => {
    let alive = true;
    void api.get<Job[]>("/api/jobs").then(async (jobs) => {
      const running = jobs.find((j) => j.ref === id && (j.status === "running" || j.status === "queued"));
      if (!running || !alive) return;
      await action.run(running.kind, async () => {
        await waitForJob(running.id, (j) => alive && setJob(j));
        if (alive) {
          setJob(null);
          await reload();
        }
      });
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (!p) return <Page title="Project">{error ? <ErrorBanner error={error} /> : <p className="muted">Loading…</p>}</Page>;

  const runJob = async (label: string, path: string, body: unknown) => {
    await action.run(label, async () => {
      const j = await api.post<Job>(path, body);
      try {
        await waitForJob(j.id, setJob);
      } finally {
        setJob(null);
        await reload();
      }
    });
  };
  const ctx: Ctx = { p, setP: (x) => setData(x), reload, action, runJob };
  const pipeline = () => runJob("pipeline", `/api/projects/${p.id}/pipeline`, { quality });
  const duplicate = () =>
    action.run("dup", async () => {
      const d = await api.post<Project>(`/api/projects/${p.id}/duplicate`);
      nav(`/projects/${d.id}`);
    });
  const remove = () =>
    action.run("del", async () => {
      if (!window.confirm(`Delete project "${p.title}"? Exported files are kept.`)) return;
      await api.del(`/api/projects/${p.id}`);
      nav(`/projects?campaign=${p.campaign_id}`);
    });
  const saveTitle = () =>
    action.run("title", async () => {
      if (title !== null && title.trim()) setData(await api.patch<Project>(`/api/projects/${p.id}`, { title: title.trim() }));
      setTitle(null);
    });

  return (
    <Page
      title={p.title}
      subtitle={
        <>
          <Link to={`/campaigns/${p.campaign_id}`}>{p.campaign?.name}</Link> · <StatusBadge status={p.status} /> · template {p.template_id} · seed {p.seed}
        </>
      }
      actions={
        <>
          <select value={quality} onChange={(e) => setQuality(e.target.value as "draft" | "final")} aria-label="pipeline quality">
            <option value="draft">Draft</option>
            <option value="final">Final</option>
          </select>
          <Button kind="primary" onClick={() => void pipeline()} busy={action.busy === "pipeline"} disabled={locked(p) || !!job} title="Script → voice → timeline → render → QA, reusing finished steps">
            Run full pipeline
          </Button>
          <Button onClick={duplicate} busy={action.busy === "dup"}>
            Duplicate
          </Button>
          <Button kind="ghost" onClick={remove}>
            Delete
          </Button>
        </>
      }
    >
      <StageStepper stages={p.stages} />
      <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
      <JobBar job={job} />
      <div className="row gap" style={{ marginBottom: 12 }}>
        <input value={title ?? p.title} onChange={(e) => setTitle(e.target.value)} aria-label="title" style={{ maxWidth: 420 }} />
        {title !== null && title !== p.title && (
          <Button onClick={saveTitle} busy={action.busy === "title"}>
            Rename
          </Button>
        )}
      </div>
      <div className="tabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)} role="tab" aria-selected={tab === key}>
            {label}
          </button>
        ))}
      </div>
      {tab === "script" && <ScriptTab {...ctx} />}
      {tab === "voice" && <VoiceTab {...ctx} />}
      {tab === "footage" && <FootageTab {...ctx} />}
      {tab === "timeline" && <TimelineTab {...ctx} />}
      {tab === "review" && <ReviewTab {...ctx} />}
      {tab === "publish" && <PublishTab {...ctx} />}
      {tab === "history" && <HistoryTab {...ctx} />}
    </Page>
  );
}
