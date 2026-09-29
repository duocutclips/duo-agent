export function fmtTime(t: number | null | undefined): string {
  if (t === null || t === undefined || Number.isNaN(t)) return "–";
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${String(m).padStart(2, "0")}:${s.toFixed(2).padStart(5, "0")}`;
}

export function fmtDuration(t: number | null | undefined): string {
  if (t === null || t === undefined) return "–";
  return t >= 60 ? `${Math.floor(t / 60)}m ${Math.round(t % 60)}s` : `${t.toFixed(1)}s`;
}

export function fmtBytes(n: number | null | undefined): string {
  if (!n) return "–";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function fmtNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  return new Intl.NumberFormat("en-US").format(n);
}

export function fmtMoney(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** Parse "mm:ss.xx", "ss.xx" or plain seconds. Returns null when invalid. */
export function parseTime(s: string): number | null {
  const t = s.trim();
  if (!t) return null;
  const parts = t.split(":");
  if (parts.length > 2) return null;
  const nums = parts.map(Number);
  if (nums.some((n) => Number.isNaN(n) || n < 0)) return null;
  return parts.length === 2 ? nums[0] * 60 + nums[1] : nums[0];
}

export function lines(text: string): string[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
}

export const CATEGORY_LABEL: Record<string, string> = {
  discovery: "Discovery",
  secret: "Secret",
  challenge: "Challenge",
  progression: "Progression",
  mistake: "Mistake",
  tutorial: "Tutorial",
  rare_item: "Rare item",
  funny_moment: "Funny moment",
  comparison: "Comparison",
  surprising_mechanic: "Surprising mechanic",
};
