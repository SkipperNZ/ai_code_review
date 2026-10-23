import { createHash } from "node:crypto";
import { Type } from "typebox";
import type { ToolDefinition } from "@earendil-works/pi-coding-agent";

export type Snapshot = {
  id: string; commit_sha: string; partial: boolean;
  files: Record<string, {text: string; text_sha256: string}>;
};
export type Chunk = {source_chunk_id: string; snapshot_id: string; commit_sha: string; path: string; start_line: number; end_line: number; excerpt: string};
export type DisplayChunk = Omit<Chunk, "excerpt"> & {numbered_excerpt: string};
export type Limits = {max_tool_calls: number; max_turns: number; max_source_chars: number; max_input_chars: number; max_generated_tokens: number; max_read_lines: number; max_tool_chars: number; wall_seconds: number};

export function safePath(path: string): boolean {
  return !!path && !path.startsWith("/") && !path.includes("\\") && !path.includes(":") && path.split("/").every(p => p !== "" && p !== "." && p !== "..");
}

export function linesOf(text: string): string[] {
  const lines = text.replaceAll("\r\n", "\n").replaceAll("\r", "\n").split("\n");
  if (lines.at(-1) === "") lines.pop();
  return lines;
}

// Presentation is not canonical evidence: IDs and stored quotes retain the exact source text.
export function displayChunk(chunk: Chunk): DisplayChunk {
  const {excerpt, ...identity} = chunk;
  return {...identity, numbered_excerpt: excerpt.split("\n").map((line, i) => `${chunk.start_line + i} | ${line}`).join("\n")};
}

export function makeChunk(snapshot: Snapshot, path: string, start: number, end: number): Chunk {
  if (!safePath(path) || !Object.hasOwn(snapshot.files, path)) throw new Error("path_not_in_snapshot");
  const lines = linesOf(snapshot.files[path].text);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || start > end || end > lines.length) throw new Error("invalid_line_range");
  const excerpt = lines.slice(start - 1, end).join("\n");
  const source_chunk_id = createHash("sha256").update([snapshot.id, path, String(start), String(end), excerpt].join("\n")).digest("hex").slice(0, 24);
  return {source_chunk_id, snapshot_id: snapshot.id, commit_sha: snapshot.commit_sha, path, start_line: start, end_line: end, excerpt};
}

export class SnapshotTools {
  readonly snapshot: Snapshot;
  readonly limits: Limits;
  readonly shown = new Map<string, Chunk>();
  sourceChars = 0;
  calls = 0;
  exhausted = false;
  readonly diff: {path: string; hunk: string; side: string} | null;
  constructor(snapshot: Snapshot, limits: Limits, initial: Chunk[], diff: {path: string; hunk: string; side: string} | null = null) {
    this.snapshot = snapshot; this.limits = limits;
    this.diff = diff;
    for (const c of initial) this.record(c);
  }
  record(c: Chunk): Chunk {
    if (!this.shown.has(c.source_chunk_id)) {
      if (this.sourceChars + c.excerpt.length > this.limits.max_source_chars) throw new Error("source_budget_exhausted");
      this.shown.set(c.source_chunk_id, c); this.sourceChars += c.excerpt.length;
    }
    return c;
  }
  guard(snapshot_id: string) {
    this.calls++;
    if (this.calls > this.limits.max_tool_calls) { this.exhausted = true; throw new Error("tool_budget_exhausted"); }
    if (snapshot_id !== this.snapshot.id) throw new Error("unknown_snapshot");
  }
  read(path: string, start: number, end: number) {
    if (!safePath(path) || !Object.hasOwn(this.snapshot.files, path)) {
      throw new Error(JSON.stringify({error: "path_not_in_snapshot", suggested_paths: this.pathHints(path), hint: "Use an exact returned path; discovery does not read its contents."}));
    }
    const total = linesOf(this.snapshot.files[path].text).length;
    if (start < 1 || start > end || end > total) throw new Error(JSON.stringify({error: "invalid_line_range", path, total_lines: total, max_read_lines: this.limits.max_read_lines}));
    if (end - start + 1 > this.limits.max_read_lines) throw new Error(`read_limit_exceeded: at most ${this.limits.max_read_lines} lines per call`);
    const c = makeChunk(this.snapshot, path, start, end);
    if (JSON.stringify(displayChunk(c)).length > this.limits.max_tool_chars) throw new Error("tool_output_limit_exceeded_use_smaller_range");
    return this.record(c);
  }
  pathHints(requested: string): {path: string; lines: number}[] {
    if (!safePath(requested)) return [];
    const name = requested.split("/").at(-1)!;
    return Object.keys(this.snapshot.files).filter(p => p.split("/").at(-1) === name).sort().slice(0, 5)
      .map(path => ({path, lines: linesOf(this.snapshot.files[path].text).length}));
  }
  definitions(): ToolDefinition[] {
    const snapshot_id = Type.String();
    const wrap = (name: string, description: string, parameters: ToolDefinition["parameters"], fn: (params: any) => unknown): ToolDefinition => ({
      name, label: name, description, parameters, executionMode: "sequential",
      execute: async (_id, params: any) => {
        this.guard(params.snapshot_id);
        const previous = new Set(this.shown.keys()), chars = this.sourceChars;
        try {
          const result = fn(params), text = JSON.stringify(result);
          if (text.length > this.limits.max_tool_chars) throw new Error("tool_output_limit_exceeded_use_smaller_limit");
          return {content: [{type: "text", text}], details: {}};
        } catch (error) {
          // A failed tool did not show any of its new chunks to the model.
          for (const key of this.shown.keys()) if (!previous.has(key)) this.shown.delete(key);
          this.sourceChars = chars;
          throw error;
        }
      },
    });
    return [
      wrap("list_paths", "List paths in the fixed snapshot. Use prefix and substring filters. No filesystem access outside the snapshot.",
        Type.Object({snapshot_id, prefix: Type.Optional(Type.String()), contains: Type.Optional(Type.String()), limit: Type.Optional(Type.Integer({minimum: 1, maximum: 80}))}),
        p => {const found = Object.keys(this.snapshot.files).filter(x => x.startsWith(p.prefix ?? "") && x.includes(p.contains ?? "")).sort(); return {paths: found.slice(0, p.limit ?? 50).map(path => ({path, lines: linesOf(this.snapshot.files[path].text).length})), total: found.length, truncated: found.length > (p.limit ?? 50), snapshot_partial: this.snapshot.partial};}),
      wrap("read_diff", "Read the anchored original diff hunk for orientation. Deleted lines are not snapshot evidence; cite read_lines chunks for verdicts.",
        Type.Object({snapshot_id}),
        () => this.diff ? {path: this.diff.path, side: this.diff.side, hunk: this.diff.hunk.slice(0, this.limits.max_tool_chars - 300), truncated: this.diff.hunk.length > this.limits.max_tool_chars - 300, citable: false} : {available: false, citable: false}),
      wrap("read_lines", `Read source lines with explicit 'line | text' numbering. Cite the chunk ID and absolute line numbers; display prefixes are not source text. At most ${this.limits.max_read_lines} lines per call. Use exact paths and line counts returned by list_paths.`,
        Type.Object({snapshot_id, path: Type.String(), start_line: Type.Integer({minimum: 1}), end_line: Type.Integer({minimum: 1})}),
        p => displayChunk(this.read(p.path, p.start_line, p.end_line))),
      wrap("search_text", "Literal case-sensitive text search over snapshot paths. Returns exact one-line evidence chunks; read surrounding lines to establish context.",
        Type.Object({snapshot_id, literal_query: Type.String({minLength: 2, maxLength: 200}), path_prefix: Type.Optional(Type.String()), limit: Type.Optional(Type.Integer({minimum: 1, maximum: 15}))}),
        p => {
          const hits: DisplayChunk[] = []; let truncated = false;
          const paths = Object.keys(this.snapshot.files).filter(path => path.startsWith(p.path_prefix ?? "")).sort();
          const result = () => ({hits, truncated, searched_paths: paths.length, snapshot_partial: this.snapshot.partial,
            ...(paths.length === 0 ? {suggested_paths: this.pathHints(p.path_prefix ?? ""), hint: "No paths matched the prefix. This search did not inspect file contents."} : {})});
          outer: for (const path of paths) {
            const lines = linesOf(this.snapshot.files[path].text);
            for (let i = 0; i < lines.length; i++) {
              if (!lines[i].includes(p.literal_query)) continue;
              if (hits.length >= (p.limit ?? 10)) { truncated = true; break outer; }
              const c = makeChunk(this.snapshot, path, i + 1, i + 1);
              hits.push(displayChunk(c));
              if (JSON.stringify(result()).length > this.limits.max_tool_chars) {hits.pop(); truncated = true; break outer;}
              this.record(c);
            }
          }
          return result();
        }),
    ];
  }
}
