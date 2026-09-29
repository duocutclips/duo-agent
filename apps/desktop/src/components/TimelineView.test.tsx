import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Timeline, TimelineItem } from "../types";
import TimelineView, { itemEnd, retimeCaption } from "./TimelineView";

const caption: TimelineItem = {
  type: "caption",
  start: 1,
  end: 2,
  text: "use code HEIST50",
  words: [
    { text: "use", start: 1, end: 1.3 },
    { text: "code", start: 1.3, end: 1.6 },
    { text: "HEIST50", start: 1.6, end: 2, emphasis: true },
  ],
};

describe("retimeCaption", () => {
  it("keeps word timings when the word count is unchanged", () => {
    const out = retimeCaption(caption, "Use code  HEIST50!");
    expect(out.text).toBe("Use code HEIST50!");
    expect(out.words).toEqual([
      { text: "Use", start: 1, end: 1.3 },
      { text: "code", start: 1.3, end: 1.6 },
      { text: "HEIST50!", start: 1.6, end: 2, emphasis: true },
    ]);
  });

  it("spreads words evenly when the count changes", () => {
    const out = retimeCaption(caption, "play now");
    expect(out.words).toEqual([
      { text: "play", start: 1, end: 1.5 },
      { text: "now", start: 1.5, end: 2 },
    ]);
  });
});

describe("TimelineView", () => {
  it("draws one block per item on the right tracks", () => {
    const tl: Timeline = {
      version: 1,
      width: 1080,
      height: 1920,
      fps: 30,
      duration: 4,
      items: [
        { type: "video", start: 0, end: 2, label: "High action" },
        { type: "video", start: 2, end: 4, label: "Calm" },
        { type: "zoom", start: 1, duration: 0.5, scale: 1.12 },
        { type: "sfx", start: 2, category: "whoosh" },
        caption,
      ],
    };
    const { container } = render(<TimelineView timeline={tl} />);
    expect(screen.getByText("Video (2)")).toBeTruthy();
    expect(screen.getByText("High action")).toBeTruthy();
    expect(container.querySelectorAll(".tl-video")).toHaveLength(2);
    expect(container.querySelectorAll(".tl-sfx")).toHaveLength(1);
    expect(itemEnd({ type: "zoom", start: 1, duration: 0.5 }, 4)).toBe(1.5);
    expect(itemEnd({ type: "music" }, 4)).toBe(4);
  });
});
