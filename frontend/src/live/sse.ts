/** Incremental Server-Sent Events parser. Feed it text chunks of any size; it returns the JSON
 *  payload of every frame completed so far. Comment lines (keepalives) and frames whose data is
 *  not valid JSON are skipped without affecting later frames. */
export class SseParser {
  private buffer = "";

  push(text: string): unknown[] {
    this.buffer = (this.buffer + text).replace(/\r\n/g, "\n");
    const out: unknown[] = [];
    let end: number;
    while ((end = this.buffer.indexOf("\n\n")) !== -1) {
      const frame = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      const data: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
      }
      if (data.length === 0) continue; // comment-only frame
      try { out.push(JSON.parse(data.join("\n"))); } catch { /* malformed frame: skip */ }
    }
    return out;
  }
}
