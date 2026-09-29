import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Button, Card, ErrorBanner, Field, Notice, Page } from "../components/ui";
import { useAction, useApi } from "../hooks";
import type { Template } from "../types";

type Obj = Record<string, unknown>;

/** Form controls for the settings people change most; everything else is editable as JSON. */
const NUMBER_FIELDS: [string, string, string, number][] = [
  ["duration", "target", "Target length (s)", 1],
  ["pacing", "min_cut", "Shortest shot (s)", 0.1],
  ["pacing", "max_cut", "Longest shot (s)", 0.1],
  ["zoom", "intensity", "Zoom intensity", 0.01],
  ["zoom", "every_n_cuts", "Zoom every N cuts (0 = off)", 1],
  ["sfx", "density", "SFX density (0–1)", 0.05],
  ["sfx", "volume", "SFX volume", 0.05],
  ["music", "volume", "Music volume", 0.01],
  ["music", "duck_to", "Duck music to (under voice)", 0.05],
  ["captions", "size", "Caption size", 1],
  ["captions", "max_words", "Words per caption", 1],
  ["captions", "stroke_width", "Caption outline", 1],
];
const COLOR_FIELDS: [string, string][] = [
  ["primary", "Caption colour"],
  ["highlight", "Highlight colour"],
  ["stroke", "Outline colour"],
];

function get(t: Obj, sec: string, key: string): unknown {
  return (t[sec] as Obj | undefined)?.[key];
}
function set(t: Obj, sec: string, key: string, v: unknown): Obj {
  return { ...t, [sec]: { ...((t[sec] as Obj) ?? {}), [key]: v } };
}

export default function Templates() {
  const list = useApi<Template[]>("/api/templates");
  const [selected, setSelected] = useState("");
  const [draft, setDraft] = useState<Obj | null>(null);
  const [json, setJson] = useState<string | null>(null);
  const action = useAction();

  useEffect(() => {
    if (!selected && list.data?.length) setSelected(list.data[0].id);
  }, [list.data, selected]);
  useEffect(() => {
    const t = list.data?.find((x) => x.id === selected);
    setDraft(t ? { ...t } : null);
    setJson(null);
  }, [selected, list.data]);

  const current = list.data?.find((x) => x.id === selected);
  const save = (t: Obj) =>
    action.run("save", async () => {
      const saved = await api.put<Template>(`/api/templates/${String(t.id)}`, t);
      await list.reload();
      setSelected(saved.id);
    }, "Template saved. New timelines built with it will use these settings.");
  const saveCopy = () => {
    if (!draft) return;
    const id = window.prompt("New template id (lowercase letters, digits, - or _):", `${String(draft.id)}_custom`);
    if (!id) return;
    void save({ ...draft, id, name: `${String(draft.name)} (custom)` });
  };
  const remove = () =>
    action.run("del", async () => {
      await api.del(`/api/templates/${selected}`);
      setSelected("");
      await list.reload();
    });

  return (
    <Page title="Templates" subtitle="Editing styles are data: pacing, zooms, captions, SFX, music and cards. Built-ins are read-only; save a copy to customise.">
      <ErrorBanner error={action.error ?? list.error} onClose={() => action.setError(null)} />
      {action.notice && <Notice tone="good">{action.notice}</Notice>}
      <div className="grid" style={{ gridTemplateColumns: "240px 1fr" }}>
        <Card title="Templates">
          <ul className="item-list">
            {list.data?.map((t) => (
              <li key={t.id}>
                <button className={`btn btn-ghost`} style={{ fontWeight: t.id === selected ? 700 : 400 }} onClick={() => setSelected(t.id)}>
                  {t.name}
                </button>{" "}
                {t.builtin ? <Badge>built-in</Badge> : <Badge tone="accent">{t.overrides_builtin ? "override" : "custom"}</Badge>}
              </li>
            ))}
          </ul>
        </Card>
        {draft && current && (
          <Card
            title={
              <>
                {String(draft.name)} <span className="muted small mono">{String(draft.id)}</span>
              </>
            }
            actions={
              <>
                <Button onClick={() => setJson(JSON.stringify(draft, null, 2))}>Edit JSON</Button>
                <Button onClick={saveCopy} busy={action.busy === "save" && current.builtin}>
                  Save as copy
                </Button>
                {!current.builtin && (
                  <>
                    <Button kind="primary" onClick={() => void save(draft)} busy={action.busy === "save"}>
                      Save
                    </Button>
                    <Button kind="ghost" onClick={remove} busy={action.busy === "del"}>
                      {current.overrides_builtin ? "Reset to built-in" : "Delete"}
                    </Button>
                  </>
                )}
              </>
            }
          >
            <p className="muted">{String(draft.description ?? "")}</p>
            <div className="grid grid-3">
              <Field label="Name">
                <input value={String(draft.name)} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              </Field>
              <Field label="Landscape footage fit">
                <select value={String(draft.fit)} onChange={(e) => setDraft({ ...draft, fit: e.target.value })}>
                  <option value="blur">Blurred background</option>
                  <option value="crop">Crop to fill</option>
                </select>
              </Field>
              <Field label="Caption position">
                <select value={String(get(draft, "captions", "position"))} onChange={(e) => setDraft(set(draft, "captions", "position", e.target.value))}>
                  <option value="lower_third">Lower third</option>
                  <option value="center">Center</option>
                  <option value="top">Top</option>
                </select>
              </Field>
              {NUMBER_FIELDS.map(([sec, key, label, step]) => (
                <Field key={sec + key} label={label}>
                  <input type="number" step={step} value={Number(get(draft, sec, key) ?? 0)} onChange={(e) => setDraft(set(draft, sec, key, Number(e.target.value)))} />
                </Field>
              ))}
              {COLOR_FIELDS.map(([key, label]) => (
                <Field key={key} label={label}>
                  <input type="color" value={String(get(draft, "captions", key) ?? "#ffffff")} onChange={(e) => setDraft(set(draft, "captions", key, e.target.value.toUpperCase()))} />
                </Field>
              ))}
            </div>
            <div className="row gap">
              <label className="check">
                <input type="checkbox" checked={Boolean(get(draft, "captions", "uppercase"))} onChange={(e) => setDraft(set(draft, "captions", "uppercase", e.target.checked))} />
                Uppercase captions
              </label>
              <label className="check">
                <input type="checkbox" checked={Boolean(get(draft, "captions", "word_emphasis"))} onChange={(e) => setDraft(set(draft, "captions", "word_emphasis", e.target.checked))} />
                Highlight the spoken word
              </label>
              <label className="check">
                <input type="checkbox" checked={Boolean(get(draft, "hook", "title_card"))} onChange={(e) => setDraft(set(draft, "hook", "title_card", e.target.checked))} />
                Hook title card
              </label>
              <label className="check">
                <input type="checkbox" checked={Boolean(get(draft, "cta", "end_card"))} onChange={(e) => setDraft(set(draft, "cta", "end_card", e.target.checked))} />
                CTA end card
              </label>
              <label className="check">
                <input type="checkbox" checked={Boolean(get(draft, "music", "enabled"))} onChange={(e) => setDraft(set(draft, "music", "enabled", e.target.checked))} />
                Music
              </label>
            </div>
            {current.builtin && <p className="muted small">Built-in template: use “Save as copy” to keep your changes.</p>}
          </Card>
        )}
      </div>
      {json !== null && (
        <Card title="Template JSON" actions={<Button kind="ghost" onClick={() => setJson(null)}>Close</Button>}>
          <textarea className="mono" value={json} onChange={(e) => setJson(e.target.value)} style={{ minHeight: 380 }} aria-label="template json" />
          <Button
            kind="primary"
            onClick={() => {
              try {
                const t = JSON.parse(json) as Obj;
                setDraft(t);
                setJson(null);
              } catch (e) {
                action.setError({ code: "json", message: "That is not valid JSON.", detail: String(e) });
              }
            }}
          >
            Apply to form
          </Button>
        </Card>
      )}
    </Page>
  );
}
