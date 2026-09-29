import { describe, expect, it } from "vitest";
import { fmtBytes, fmtDuration, fmtMoney, fmtNumber, fmtTime, lines, parseTime } from "./format";

describe("format helpers", () => {
  it("formats timestamps and durations", () => {
    expect(fmtTime(0)).toBe("00:00.00");
    expect(fmtTime(75.5)).toBe("01:15.50");
    expect(fmtTime(null)).toBe("–");
    expect(fmtDuration(12.34)).toBe("12.3s");
    expect(fmtDuration(95)).toBe("1m 35s");
  });

  it("parses user-entered times", () => {
    expect(parseTime("1:15.5")).toBe(75.5);
    expect(parseTime("12.25")).toBe(12.25);
    expect(parseTime("")).toBeNull();
    expect(parseTime("a:b")).toBeNull();
    expect(parseTime("1:2:3")).toBeNull();
    expect(parseTime("-4")).toBeNull();
  });

  it("formats sizes, numbers and money", () => {
    expect(fmtBytes(0)).toBe("–");
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(1536)).toBe("1.5 KB");
    expect(fmtBytes(25 * 1024 * 1024)).toBe("25 MB");
    expect(fmtNumber(1234567)).toBe("1,234,567");
    expect(fmtMoney(6)).toBe("$6.00");
    expect(fmtMoney(null)).toBe("–");
  });

  it("splits non-empty lines", () => {
    expect(lines(" a \n\n b\n")).toEqual(["a", "b"]);
  });
});
