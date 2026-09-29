import { useEffect, useState } from "react";
import { api } from "../api";
import { useAction } from "../hooks";
import type { Script } from "../types";
import { Badge, Button, ErrorBanner, Field, Notice } from "./ui";

const TARGETS = [15, 20, 30, 45];

interface Estimate {
  est_seconds: number;
  warnings: string[];
  word_count: number;
}

export default function ScriptEditor({ script, onSaved }: { script: Script; onSaved?: (s: Script) => void }) {
  const [text, setText] = useState(script.text);
  const [target, setTarget] = useState(script.target_seconds);
  const [est, setEst] = useState<Estimate>({ est_seconds: script.est_seconds, warnings: script.warnings, word_count: script.text.split(/\s+/).length });
  const action = useAction();

  useEffect(() => {
    setText(script.text);
    setTarget(script.target_seconds);
  }, [script.id, script.text, script.target_seconds]);

  useEffect(() => {
    const t = setTimeout(() => {
      api
        .post<Estimate>("/api/scripts/estimate", { text, target_seconds: target, campaign_id: script.campaign_id })
        .then(setEst)
        .catch(() => undefined);
    }, 300);
    return () => clearTimeout(t);
  }, [text, target, script.campaign_id]);

  const save = () =>
    action.run("save", async () => {
      const s = await api.put<Script>(`/api/scripts/${script.id}`, { text, target_seconds: target });
      onSaved?.(s);
    }, "Script saved.");

  const over = est.est_seconds > target * 1.05;
  return (
    <div>
      <ErrorBanner error={action.error} onClose={() => action.setError(null)} />
      <div className="row gap spread">
        <div className="row gap">
          <Field label="Target duration">
            <select value={target} onChange={(e) => setTarget(Number(e.target.value))} style={{ width: 110 }}>
              {TARGETS.map((t) => (
                <option key={t} value={t}>
                  {t} sec
                </option>
              ))}
            </select>
          </Field>
          <div>
            <div className="field-label">Estimated speaking time</div>
            <Badge tone={over ? "bad" : est.est_seconds < target * 0.6 ? "warn" : "good"}>
              ~{est.est_seconds.toFixed(1)}s · {est.word_count} words
            </Badge>
          </div>
        </div>
        <span className="muted small">generator: {script.generator}</span>
      </div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} style={{ minHeight: 150 }} aria-label="script text" />
      {est.warnings.map((w) => (
        <Notice key={w} tone="warn">
          {w}
        </Notice>
      ))}
      <div className="row gap" style={{ marginTop: 8 }}>
        <Button kind="primary" onClick={save} busy={action.busy === "save"} disabled={text === script.text && target === script.target_seconds}>
          Save script
        </Button>
        {action.notice && <span className="muted">{action.notice}</span>}
      </div>
    </div>
  );
}
