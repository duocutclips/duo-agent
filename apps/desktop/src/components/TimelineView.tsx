import type { Timeline, TimelineItem } from "../types";

const TRACKS: { name: string; types: TimelineItem["type"][]; cls: string }[] = [
  { name: "Video", types: ["video"], cls: "tl-video" },
  { name: "Zoom", types: ["zoom"], cls: "tl-zoom" },
  { name: "Title / CTA", types: ["text"], cls: "tl-text" },
  { name: "Captions", types: ["caption"], cls: "tl-caption" },
  { name: "Voice / music", types: ["narration", "music"], cls: "tl-audio" },
  { name: "SFX", types: ["sfx"], cls: "tl-sfx" },
];

export function itemEnd(it: TimelineItem, total: number): number {
  if (typeof it.end === "number") return it.end;
  if (typeof it.duration === "number") return (it.start ?? 0) + it.duration;
  return total;
}

function label(it: TimelineItem): string {
  switch (it.type) {
    case "video":
      return String(it.label || "clip");
    case "zoom":
      return `×${Number(it.scale ?? 1).toFixed(2)}`;
    case "caption":
    case "text":
      return String(it.text ?? "");
    case "sfx":
      return String(it.category ?? "sfx");
    default:
      return it.type;
  }
}

/** Read-only multi-track view of a timeline; clicking the video track seeks the preview. */
export default function TimelineView({ timeline, onSeek }: { timeline: Timeline; onSeek?: (t: number) => void }) {
  const total = timeline.duration || 1;
  return (
    <div>
      {TRACKS.map((track) => {
        const items = timeline.items.filter((i) => track.types.includes(i.type));
        if (!items.length) return null;
        return (
          <div key={track.name}>
            <div className="tl-label">
              {track.name} ({items.length})
            </div>
            <div className="timeline-track">
              {items.map((it, idx) => {
                const s = it.start ?? 0;
                const e = itemEnd(it, total);
                return (
                  <div
                    key={idx}
                    className={`tl-block ${track.cls}`}
                    style={{ left: `${(s / total) * 100}%`, width: `${Math.max(0.3, ((e - s) / total) * 100)}%`, cursor: onSeek ? "pointer" : undefined }}
                    title={`${it.type} ${s.toFixed(2)}–${e.toFixed(2)}s ${label(it)}${it.reason ? " · " + String(it.reason) : ""}`}
                    onClick={() => onSeek?.(s)}
                  >
                    {track.cls !== "tl-sfx" && label(it)}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Re-time caption words after the user edits the caption text. */
export function retimeCaption(it: TimelineItem, text: string): TimelineItem {
  const words = text.split(/\s+/).filter(Boolean);
  const old = (it.words as { text: string; start: number; end: number }[] | undefined) ?? [];
  const start = it.start ?? 0;
  const end = it.end ?? start;
  let next: { text: string; start: number; end: number }[];
  if (old.length === words.length) {
    next = old.map((w, i) => ({ ...w, text: words[i] }));
  } else {
    const step = words.length ? (end - start) / words.length : 0;
    next = words.map((w, i) => ({ text: w, start: +(start + i * step).toFixed(3), end: +(start + (i + 1) * step).toFixed(3) }));
  }
  return { ...it, text: words.join(" "), words: next };
}
