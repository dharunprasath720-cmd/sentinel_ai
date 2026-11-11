import { describe, expect, it } from "vitest";
import { SseParser } from "./sse";

describe("SseParser", () => {
  it("splits a frame across chunks", () => {
    const p = new SseParser();
    expect(p.push('data: {"a":')).toEqual([]);
    expect(p.push("1}\n\n")).toEqual([{ a: 1 }]);
  });

  it("handles CRLF line endings, even when CR and LF arrive in different chunks", () => {
    const p = new SseParser();
    expect(p.push('data: {"a":1}\r\n\r')).toEqual([]);
    expect(p.push("\n")).toEqual([{ a: 1 }]);
  });

  it("joins multi-line data fields", () => {
    expect(new SseParser().push('data: {"a":\ndata: 1}\n\n')).toEqual([{ a: 1 }]);
  });

  it("ignores keepalive comments", () => {
    const p = new SseParser();
    expect(p.push(": connected\n\n: keepalive\n\n")).toEqual([]);
  });

  it("skips a malformed JSON frame and still parses the next one", () => {
    const out = new SseParser().push('data: {not json}\n\ndata: {"ok":true}\n\n');
    expect(out).toEqual([{ ok: true }]);
  });

  it("returns several frames from one chunk in order", () => {
    expect(new SseParser().push('data: {"n":1}\n\ndata: {"n":2}\n\n')).toEqual([{ n: 1 }, { n: 2 }]);
  });
});
