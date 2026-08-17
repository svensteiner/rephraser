import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_PROTECTED_TERM_MATCHES,
  MODE_FAST,
  MODE_SAFE,
  createContentlessAudit,
  decodeTextFileBytes,
  inspectText,
  normalizeProtectedTerms,
  transformText,
} from "../web/editor.js";

test("safe browser cleanup normalizes copy/paste artifacts but retains unknown formats and emoji", () => {
  const source = "\uFEFFCafe\u0301\r\nA\u200B\u00AD\u00A0B\u202FC 👨‍👩‍👧‍👦\u2066";
  const result = transformText(source, { mode: MODE_SAFE });

  assert.equal(result.blocked, false);
  assert.equal(result.rewritten, "Café\nA B C 👨‍👩‍👧‍👦\u2066");
  assert.ok(result.rewritten.includes("👨‍👩‍👧‍👦"));
  assert.ok(result.rewritten.includes("\u2066"));
  assert.ok(result.before_inspection.character_summary.some((item) => item.code_point === "U+2066"));
  assert.ok(result.after_inspection.character_summary.some((item) => item.code_point === "U+2066"));
});

test("unknown Unicode format characters are reported, retained, and rejected as protected terms", () => {
  const source = "A\uFFF9B\u206AC\u{E0001}D";
  const result = transformText(source, { mode: MODE_SAFE });
  const reported = result.before_inspection.character_summary.map((item) => item.code_point);
  const protectedTerms = normalizeProtectedTerms(["A\uFFF9B"]);

  assert.equal(result.rewritten, source);
  assert.deepEqual(reported, ["U+206A", "U+FFF9", "U+E0001"]);
  assert.equal(protectedTerms.terms.length, 0);
  assert.equal(protectedTerms.errors.length, 1);
});

test("local file decoder preserves a BOM and rejects unknown encodings", () => {
  assert.equal(decodeTextFileBytes(Uint8Array.of(0xef, 0xbb, 0xbf, 0x41)), "\uFEFFA");
  assert.equal(decodeTextFileBytes(Uint8Array.of(0xff, 0xfe, 0x41, 0x00)), "\uFEFFA");
  assert.equal(decodeTextFileBytes(Uint8Array.of(0xfe, 0xff, 0x00, 0x41)), "\uFEFFA");
  assert.throws(() => decodeTextFileBytes(Uint8Array.of(0xc3, 0x28)), /UTF-8 oder UTF-16/);
});

test("fast browser rules improve only ordinary prose", () => {
  const source = [
    "---\ntitle: \"We would like to better understand\"\n---",
    "> We would like to better understand the history.",
    "`We would like to better understand the code.`",
    "[Link](https://example.test/We-would-like-to-better-understand)",
    "We would like to better understand the report.",
  ].join("\n\n");
  const result = transformText(source, { mode: MODE_FAST });

  assert.equal(result.blocked, false);
  assert.ok(result.rewritten.includes('title: "We would like to better understand"'));
  assert.ok(result.rewritten.includes("> We would like to better understand the history."));
  assert.ok(result.rewritten.includes("`We would like to better understand the code.`"));
  assert.ok(result.rewritten.includes("https://example.test/We-would-like-to-better-understand"));
  assert.ok(result.rewritten.endsWith("We would appreciate clarification on the report."));
});

test("protected terms remain exact and missing terms block browser processing", () => {
  const source = "We would like to better understand Project Aurora.";
  const protectedResult = transformText(source, {
    mode: MODE_FAST,
    protectedTerms: ["We would like to better understand"],
  });
  const blockedResult = transformText(source, { mode: MODE_FAST, protectedTerms: ["Nicht vorhanden"] });

  assert.equal(protectedResult.rewritten, source);
  assert.equal(blockedResult.blocked, true);
  assert.deepEqual(blockedResult.missing_protected_terms, ["Nicht vorhanden"]);
});

test("a very frequent protected term is blocked before it can freeze the browser", () => {
  const result = transformText("a".repeat(MAX_PROTECTED_TERM_MATCHES + 1), {
    mode: MODE_SAFE,
    protectedTerms: ["a"],
  });

  assert.equal(result.blocked, true);
  assert.match(result.errors[0], /spezifischeren Begriff/);
});

test("browser rules do not rewrite high-risk legal, modal, or direction terms", () => {
  const source = "The contract permits transfer. Revenue may increase. Die Gesellschaft darf zahlen. The control is effective.";
  const result = transformText(source, { mode: MODE_FAST });

  assert.equal(result.rewritten, source);
});

test("inspection groups positions and contentless audit excludes text and protected terms", async () => {
  const inspection = inspectText("A\u200BB\u200B\u2066");
  const zeroWidth = inspection.character_summary.find((item) => item.code_point === "U+200B");
  assert.equal(zeroWidth.count, 2);
  assert.deepEqual(zeroWidth.positions, [1, 3]);

  const result = transformText("We would like to better understand Project Aurora.", {
    mode: MODE_FAST,
    protectedTerms: ["Project Aurora"],
  });
  const audit = await createContentlessAudit(result);
  assert.equal(audit.provider, "browser-fast-editor");
  assert.equal(audit.content_included, false);
  assert.ok(audit.input_sha256);
  assert.equal(JSON.stringify(audit).includes("We would like to better understand"), false);
  assert.equal(JSON.stringify(audit).includes("Project Aurora"), false);
  assert.equal(audit.protected_term_count, 1);
});
