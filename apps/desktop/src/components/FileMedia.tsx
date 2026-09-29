import { forwardRef, useEffect, useState } from "react";
import { fileUrl } from "../api";

export function useFileUrl(path: string | null, bust?: string): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    if (!path) {
      setUrl(null);
      return;
    }
    void fileUrl(path, bust).then((u) => alive && setUrl(u));
    return () => {
      alive = false;
    };
  }, [path, bust]);
  return url;
}

export function Thumb({ path, className, alt }: { path: string | null; className?: string; alt?: string }) {
  const url = useFileUrl(path);
  if (!url) return <div className={className ?? "thumb"} />;
  return <img src={url} className={className ?? "thumb"} alt={alt ?? ""} />;
}

export const Video = forwardRef<HTMLVideoElement, { path: string | null; bust?: string; className?: string }>(function Video(
  { path, bust, className },
  ref,
) {
  const url = useFileUrl(path, bust);
  if (!url) return null;
  return <video ref={ref} src={url} className={className ?? "preview-video"} controls preload="metadata" />;
});

export function Audio({ path, bust }: { path: string | null; bust?: string }) {
  const url = useFileUrl(path, bust);
  if (!url) return null;
  return <audio src={url} controls preload="none" style={{ width: "100%" }} />;
}

export function Curve({ values, color, min, max }: { values: number[]; color: string; min?: number; max?: number }) {
  if (!values.length) return null;
  const lo = min ?? Math.min(...values);
  const hi = max ?? Math.max(...values);
  const span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / Math.max(1, values.length - 1)) * 100},${50 - ((Math.max(lo, Math.min(hi, v)) - lo) / span) * 46 - 2}`).join(" ");
  return (
    <svg className="curve" viewBox="0 0 100 50" preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="0.8" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
