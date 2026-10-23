import assert from "node:assert/strict";
import test from "node:test";
import {displayChunk, makeChunk, safePath, SnapshotTools, type Limits, type Snapshot} from "./tools.ts";

const snapshot: Snapshot = {id: "snap-test", commit_sha: "a".repeat(40), partial: false, files: {"a.py": {text: "one\ntwo\nthree\n", text_sha256: "unused"}}};
const limits: Limits = {max_tool_calls: 2, max_turns: 3, max_source_chars: 100, max_input_chars: 1000, max_generated_tokens: 100, max_read_lines: 2, max_tool_chars: 1000, wall_seconds: 20};

test("in-memory paths prevent filesystem escapes", () => {
  for (const path of ["../secret", "C:/secret", "a\\b", "/secret", "a/./b"]) assert.equal(safePath(path), false);
  assert.throws(() => makeChunk(snapshot, "../secret", 1, 1));
});
test("chunks preserve exact inclusive lines", () => {
  assert.equal(makeChunk(snapshot, "a.py", 2, 3).excerpt, "two\nthree");
  assert.throws(() => makeChunk(snapshot, "a.py", 1, 4));
});
test("source and tool budgets fail before exposing extra data", () => {
  const t = new SnapshotTools(snapshot, {...limits, max_source_chars: 4}, []);
  assert.equal(t.read("a.py", 1, 1).excerpt, "one");
  assert.throws(() => t.read("a.py", 2, 3));
  assert.equal(t.shown.size, 1);
  t.guard(snapshot.id); t.guard(snapshot.id); assert.throws(() => t.guard(snapshot.id));
  assert.equal(t.exhausted, true);
});

test("numbered display preserves blank lines and canonical identities", () => {
  const s = {...snapshot, files: {"blank.py": {text: "first\n\nthird\n", text_sha256: "unused"}}};
  const canonical = makeChunk(s, "blank.py", 2, 3);
  const before = JSON.stringify(canonical);
  const display = displayChunk(canonical);
  assert.equal(display.numbered_excerpt, "2 | \n3 | third");
  assert.equal(display.source_chunk_id, canonical.source_chunk_id);
  assert.equal("excerpt" in display, false);
  assert.equal(JSON.stringify(canonical), before);
});

test("display overhead is included in tool output budget", () => {
  const c = makeChunk(snapshot, "a.py", 1, 1);
  const t = new SnapshotTools(snapshot, {...limits, max_tool_chars: JSON.stringify(c).length}, []);
  assert.throws(() => t.read("a.py", 1, 1), /tool_output_limit/);
  assert.equal(t.shown.size, 0);
  assert.equal(t.sourceChars, 0);
});

test("bad paths and ranges provide bounded recovery without reading evidence", () => {
  const s = {...snapshot, files: {"tests/basics/run_all.py": snapshot.files["a.py"]}};
  const t = new SnapshotTools(s, limits, []);
  assert.throws(() => t.read("tests/run_all.py", 1, 2), /tests\/basics\/run_all.py/);
  assert.throws(() => t.read("tests/basics/run_all.py", 1, 50), /"total_lines":3/);
  assert.deepEqual(t.pathHints("../run_all.py"), []);
  assert.equal(t.shown.size, 0);
});

async function invoke(t: SnapshotTools, name: string, params: Record<string, unknown>) {
  const tool = t.definitions().find(d => d.name === name)!;
  const response = await tool.execute("test-call", {snapshot_id: t.snapshot.id, ...params}, undefined, undefined, {} as never);
  const content = response.content[0];
  assert.equal(content.type, "text");
  return JSON.parse((content as {text: string}).text);
}

test("search distinguishes unmatched paths from absent text and suggests actual paths", async () => {
  const s = {...snapshot, files: {"tests/basics/run_all.py": snapshot.files["a.py"]}};
  const t = new SnapshotTools(s, {...limits, max_tool_calls: 3}, []);
  const wrong = await invoke(t, "search_text", {path_prefix: "tests/run_all.py", literal_query: "two"});
  assert.equal(wrong.searched_paths, 0);
  assert.equal(wrong.suggested_paths[0].path, "tests/basics/run_all.py");
  assert.equal(t.shown.size, 0);
  const absent = await invoke(t, "search_text", {path_prefix: "tests/basics/run_all.py", literal_query: "missing"});
  assert.equal(absent.searched_paths, 1);
  assert.equal(absent.hits.length, 0);
  const found = await invoke(t, "search_text", {path_prefix: "tests/basics/run_all.py", literal_query: "two"});
  assert.equal(found.hits[0].numbered_excerpt, "2 | two");
  assert.equal(t.shown.get(found.hits[0].source_chunk_id)?.excerpt, "two");
});

test("failed multi-hit search rolls back all newly registered evidence", async () => {
  const s = {...snapshot, files: {"a.py": {text: "hit one\nhit two\n", text_sha256: "unused"}}};
  const t = new SnapshotTools(s, {...limits, max_source_chars: 8}, []);
  await assert.rejects(invoke(t, "search_text", {literal_query: "hit"}), /source_budget_exhausted/);
  assert.equal(t.shown.size, 0);
  assert.equal(t.sourceChars, 0);
});
