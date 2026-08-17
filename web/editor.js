/**
 * Browser-only text processing for the GitHub Pages edition.
 *
 * This module deliberately contains no network or persistent-storage code.
 * It is a small deterministic companion to the desktop application, not a
 * browser wrapper around a language model.
 */

export const BROWSER_EDITION_VERSION = "1.1.0";
export const MAX_INPUT_CHARACTERS = 2_000_000;
export const MAX_PROTECTED_TERMS = 50;
export const MAX_PROTECTED_TERM_LENGTH = 100;
export const MAX_PROTECTED_TERM_MATCHES = 2_000;
export const MAX_INPUT_FILE_BYTES = MAX_INPUT_CHARACTERS * 4 + 4;
export const MODE_FAST = "fast";
export const MODE_SAFE = "safe";

const MAX_REPORTED_POSITIONS = 1_000;

const CHARACTER_DETAILS = new Map([
  ["\u200B", { category: "Cf", kind: "zero_width", name: "ZERO WIDTH SPACE" }],
  ["\u200C", { category: "Cf", kind: "zero_width", name: "ZERO WIDTH NON-JOINER" }],
  ["\u200D", { category: "Cf", kind: "zero_width", name: "ZERO WIDTH JOINER" }],
  ["\uFEFF", { category: "Cf", kind: "BOM", name: "ZERO WIDTH NO-BREAK SPACE" }],
  ["\u00AD", { category: "Cf", kind: "soft_hyphen", name: "SOFT HYPHEN" }],
  ["\u00A0", { category: "Zs", kind: "non_breaking_space", name: "NO-BREAK SPACE" }],
  ["\u202F", { category: "Zs", kind: "non_breaking_space", name: "NARROW NO-BREAK SPACE" }],
  ["\u2060", { category: "Cf", kind: "unknown_format_character", name: "WORD JOINER" }],
  ["\u2066", { category: "Cf", kind: "unknown_format_character", name: "LEFT-TO-RIGHT ISOLATE" }],
  ["\u2067", { category: "Cf", kind: "unknown_format_character", name: "RIGHT-TO-LEFT ISOLATE" }],
  ["\u2068", { category: "Cf", kind: "unknown_format_character", name: "FIRST STRONG ISOLATE" }],
  ["\u2069", { category: "Cf", kind: "unknown_format_character", name: "POP DIRECTIONAL ISOLATE" }],
  ["\u200E", { category: "Cf", kind: "unknown_format_character", name: "LEFT-TO-RIGHT MARK" }],
  ["\u200F", { category: "Cf", kind: "unknown_format_character", name: "RIGHT-TO-LEFT MARK" }],
]);

const FORMAT_CODE_POINT_RANGES = [
  [0x200b, 0x200f],
  [0x202a, 0x202e],
  [0x2060, 0x2064],
  [0x2066, 0x2069],
  [0xfeff, 0xfeff],
];

const UNUSUAL_WHITESPACE_CODE_POINTS = new Set([
  0x1680,
  0x2000,
  0x2001,
  0x2002,
  0x2003,
  0x2004,
  0x2005,
  0x2006,
  0x2007,
  0x2008,
  0x2009,
  0x200a,
  0x205f,
  0x3000,
]);

const PROTECTED_TERM_CHARACTER = /[\u0000-\u001F\u007F-\u009F\u00AD\u200B-\u200F\u202A-\u202E\u2060\u2066-\u2069\uFEFF]/u;
const FORMAT_CHARACTER = /^\p{Cf}$/u;

const PROTECTED_PROSE = /(^---\r?\n[\s\S]*?\r?\n---(?=\r?\n|$)|(?:```|~~~)[\s\S]*?(?:```|~~~)|^(?: {4}|\t).*$|^>.*$|``[^\n]*?``|`[^`\n]+`|<!--[\s\S]*?-->|<[cC][oO][dD][eE]\b[^>]*>[\s\S]*?<\/[cC][oO][dD][eE]\s*>|<[pP][rR][eE]\b[^>]*>[\s\S]*?<\/[pP][rR][eE]\s*>|<https?:\/\/[^>\n]+>|\]\([^\)\n]+\)|"[^"\n]+"|„[^“\n]+“|“[^”\n]+”|»[^«\n]+«|«[^»\n]+»|‘[^’\n]+’)/gm;

const FAST_REPLACEMENTS = [
  { label: "We would like to better understand", pattern: /\bWe would like to better understand\b/g, replacement: "We would appreciate clarification on" },
  { label: "we would like to better understand", pattern: /\bwe would like to better understand\b/g, replacement: "we would appreciate clarification on" },
  { label: "You mentioned that", pattern: /\bYou mentioned that\b/g, replacement: "You noted that" },
  { label: "Could you please clarify", pattern: /\bCould you please clarify:\s*(?=\n|$)/g, replacement: "Could you please clarify the following:" },
  { label: "In order to", pattern: /\bIn order to\b/g, replacement: "To" },
  { label: "Due to the fact that", pattern: /\bDue to the fact that\b/g, replacement: "Because" },
  { label: "due to the fact that", pattern: /\bdue to the fact that\b/g, replacement: "because" },
  { label: "At this point in time", pattern: /\bAt this point in time\b/g, replacement: "Currently" },
  { label: "Please do not hesitate to", pattern: /\bPlease do not hesitate to\b/g, replacement: "Please" },
  { label: "Wir möchten gerne", pattern: /\bWir möchten gerne\b/g, replacement: "Wir möchten" },
  { label: "Es ist wichtig zu beachten, dass", pattern: /\bEs ist wichtig zu beachten, dass\b/g, replacement: "Zu beachten ist, dass" },
  { label: "Zum jetzigen Zeitpunkt", pattern: /\bZum jetzigen Zeitpunkt\b/g, replacement: "Derzeit" },
  { label: "zum jetzigen Zeitpunkt", pattern: /\bzum jetzigen Zeitpunkt\b/g, replacement: "derzeit" },
  { label: "Aufgrund der Tatsache, dass", pattern: /\bAufgrund der Tatsache, dass\b/g, replacement: "Weil" },
  { label: "aufgrund der Tatsache, dass", pattern: /\baufgrund der Tatsache, dass\b/g, replacement: "weil" },
];

function codePointLabel(character) {
  return `U+${character.codePointAt(0).toString(16).toUpperCase().padStart(4, "0")}`;
}

function isFormatCharacter(codePoint) {
  return FORMAT_CODE_POINT_RANGES.some(([start, end]) => codePoint >= start && codePoint <= end);
}

function characterDetail(character) {
  const known = CHARACTER_DETAILS.get(character);
  if (known) {
    return known;
  }
  const codePoint = character.codePointAt(0);
  if (isFormatCharacter(codePoint)) {
    return { category: "Cf", kind: "unknown_format_character", name: "FORMAT CHARACTER" };
  }
  if (FORMAT_CHARACTER.test(character)) {
    return { category: "Cf", kind: "unknown_format_character", name: "FORMAT CHARACTER" };
  }
  if (UNUSUAL_WHITESPACE_CODE_POINTS.has(codePoint)) {
    return { category: "Zs", kind: "unusual_whitespace", name: "UNUSUAL SPACE" };
  }
  if ((codePoint <= 0x1f && ![0x09, 0x0a, 0x0d].includes(codePoint)) || (codePoint >= 0x7f && codePoint <= 0x9f)) {
    return { category: "Cc", kind: "control_character", name: "CONTROL CHARACTER" };
  }
  return null;
}

function countCodePoints(text) {
  return Array.from(text).length;
}

/** Decode local UTF-8/UTF-16 text files without silently guessing an encoding. */
export function decodeTextFileBytes(bytes) {
  if (!(bytes instanceof Uint8Array)) {
    throw new TypeError("Dateiinhalte muessen als Uint8Array vorliegen.");
  }
  let encoding = "utf-8";
  let content = bytes;
  let prefix = "";
  if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    content = bytes.slice(3);
    prefix = "\uFEFF";
  } else if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xfe) {
    encoding = "utf-16le";
    content = bytes.slice(2);
    prefix = "\uFEFF";
  } else if (bytes.length >= 2 && bytes[0] === 0xfe && bytes[1] === 0xff) {
    encoding = "utf-16be";
    content = bytes.slice(2);
    prefix = "\uFEFF";
  }
  try {
    return prefix + new TextDecoder(encoding, { fatal: true }).decode(content);
  } catch {
    throw new Error("Datei ist nicht als UTF-8 oder UTF-16 lesbar.");
  }
}

function textStatistics(text) {
  const words = text.match(/\p{L}[\p{L}\p{M}\p{N}'’-]*/gu) ?? [];
  const paragraphs = text.trim() ? text.trim().split(/\n\s*\n/u).length : 0;
  return {
    characters: countCodePoints(text),
    words: words.length,
    paragraphs,
  };
}

/** Report notable invisible/format characters without deleting unknown patterns. */
export function inspectText(text) {
  const summaries = new Map();
  let position = 0;
  for (const character of text) {
    const detail = characterDetail(character);
    if (detail) {
      const codePoint = codePointLabel(character);
      const key = `${detail.kind}:${codePoint}`;
      const existing = summaries.get(key) ?? {
        code_point: codePoint,
        name: detail.name,
        category: detail.category,
        kind: detail.kind,
        count: 0,
        positions: [],
        positions_truncated: false,
      };
      existing.count += 1;
      if (existing.positions.length < MAX_REPORTED_POSITIONS) {
        existing.positions.push(position + 1);
      } else {
        existing.positions_truncated = true;
      }
      summaries.set(key, existing);
    }
    position += 1;
  }
  const characterSummary = Array.from(summaries.values()).sort(
    (left, right) => Number.parseInt(left.code_point.slice(2), 16) - Number.parseInt(right.code_point.slice(2), 16),
  );
  return {
    statistics: textStatistics(text),
    character_summary: characterSummary,
    suspicious_character_count: characterSummary.reduce((total, item) => total + item.count, 0),
  };
}

/** Validate short, exact terms that must remain unchanged. */
export function normalizeProtectedTerms(rawTerms) {
  const source = Array.isArray(rawTerms) ? rawTerms : String(rawTerms ?? "").split(/\r?\n/u);
  const terms = [];
  const errors = [];
  for (const rawTerm of source) {
    const term = String(rawTerm).trim();
    if (!term || terms.includes(term)) {
      continue;
    }
    if (term.length > MAX_PROTECTED_TERM_LENGTH) {
      errors.push(`Ein geschützter Begriff darf höchstens ${MAX_PROTECTED_TERM_LENGTH} Zeichen haben.`);
      continue;
    }
    if (PROTECTED_TERM_CHARACTER.test(term) || Array.from(term).some((character) => FORMAT_CHARACTER.test(character))) {
      errors.push("Geschützte Begriffe dürfen keine unsichtbaren Steuer- oder Formatzeichen enthalten.");
      continue;
    }
    terms.push(term);
  }
  if (terms.length > MAX_PROTECTED_TERMS) {
    errors.push(`Es können höchstens ${MAX_PROTECTED_TERMS} Begriffe geschützt werden.`);
  }
  return { terms: terms.slice(0, MAX_PROTECTED_TERMS), errors };
}

export function missingProtectedTerms(text, terms) {
  return terms.filter((term) => !text.includes(term));
}

function literalSpans(text, terms) {
  const spans = [];
  for (const term of terms) {
    let start = 0;
    while (true) {
      const found = text.indexOf(term, start);
      if (found < 0) {
        break;
      }
      spans.push([found, found + term.length]);
      if (spans.length > MAX_PROTECTED_TERM_MATCHES) {
        throw new ProtectedTermMatchLimitError();
      }
      start = found + term.length;
    }
  }
  spans.sort((left, right) => left[0] - right[0] || right[1] - left[1]);
  const merged = [];
  for (const [start, end] of spans) {
    const last = merged.at(-1);
    if (last && start <= last[1]) {
      last[1] = Math.max(last[1], end);
    } else {
      merged.push([start, end]);
    }
  }
  return merged;
}

class ProtectedTermMatchLimitError extends Error {
  constructor() {
    super("Zu viele Fundstellen geschuetzter Begriffe.");
  }
}

function exceedsProtectedTermMatchLimit(text, terms) {
  let matchCount = 0;
  for (const term of terms) {
    let start = 0;
    while (true) {
      const found = text.indexOf(term, start);
      if (found < 0) {
        break;
      }
      matchCount += 1;
      if (matchCount > MAX_PROTECTED_TERM_MATCHES) {
        return true;
      }
      start = found + term.length;
    }
  }
  return false;
}

function protectedTermMatchLimitMessage() {
  return `Geschuetzte Begriffe kommen mehr als ${MAX_PROTECTED_TERM_MATCHES.toLocaleString("de-DE")} Mal vor. Bitte einen spezifischeren Begriff verwenden.`;
}

function transformOutsideProtectedTerms(text, terms, transform) {
  const spans = literalSpans(text, terms);
  if (!spans.length) {
    return transform(text);
  }
  const pieces = [];
  let cursor = 0;
  for (const [start, end] of spans) {
    pieces.push(transform(text.slice(cursor, start)));
    pieces.push(text.slice(start, end));
    cursor = end;
  }
  pieces.push(transform(text.slice(cursor)));
  return pieces.join("");
}

function recordChange(changes, kind, label, count) {
  if (!count) {
    return;
  }
  const existing = changes.find((change) => change.kind === kind);
  if (existing) {
    existing.count += count;
  } else {
    changes.push({ kind, label, count });
  }
}

function safeCleanFragment(fragment, changes) {
  let cleaned = fragment;
  const lineEndingCount = (cleaned.match(/\r\n|\n\r|\r/g) ?? []).length;
  cleaned = cleaned.replace(/\r\n|\n\r|\r/g, "\n");
  recordChange(changes, "line_endings", "Zeilenenden vereinheitlicht", lineEndingCount);

  const nfc = cleaned.normalize("NFC");
  if (nfc !== cleaned) {
    recordChange(changes, "nfc", "Unicode nach NFC normalisiert", 1);
    cleaned = nfc;
  }

  const zeroWidthSpaces = (cleaned.match(/\u200B/g) ?? []).length;
  cleaned = cleaned.replace(/\u200B/g, "");
  recordChange(changes, "zero_width_space", "Zero-Width-Spaces entfernt", zeroWidthSpaces);

  const softHyphens = (cleaned.match(/\u00AD/g) ?? []).length;
  cleaned = cleaned.replace(/\u00AD/g, "");
  recordChange(changes, "soft_hyphen", "Unsichtbare Trennstriche entfernt", softHyphens);

  const nonBreakingSpaces = (cleaned.match(/[\u00A0\u202F]/g) ?? []).length;
  cleaned = cleaned.replace(/[\u00A0\u202F]/g, " ");
  recordChange(changes, "non_breaking_space", "Geschützte Leerzeichen ersetzt", nonBreakingSpaces);
  return cleaned;
}

function cleanCopyPasteArtifacts(text, terms, changes) {
  let cleaned = transformOutsideProtectedTerms(text, terms, (fragment) => safeCleanFragment(fragment, changes));
  if (cleaned.startsWith("\uFEFF")) {
    cleaned = cleaned.slice(1);
    recordChange(changes, "leading_bom", "Führendes BOM entfernt", 1);
  }
  return cleaned;
}

function applyFastRulesToFragment(fragment, changes) {
  let result = fragment;
  for (const [index, rule] of FAST_REPLACEMENTS.entries()) {
    let replacements = 0;
    rule.pattern.lastIndex = 0;
    result = result.replace(rule.pattern, () => {
      replacements += 1;
      return rule.replacement;
    });
    recordChange(changes, `phrase_rule_${index + 1}`, `Feste Formulierung geglättet: ${rule.label}`, replacements);
  }
  return result;
}

function applyFastRules(text, terms, changes) {
  const pattern = new RegExp(PROTECTED_PROSE.source, PROTECTED_PROSE.flags);
  const pieces = [];
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    const start = match.index ?? cursor;
    pieces.push(transformOutsideProtectedTerms(text.slice(cursor, start), terms, (fragment) => applyFastRulesToFragment(fragment, changes)));
    pieces.push(match[0]);
    cursor = start + match[0].length;
  }
  pieces.push(transformOutsideProtectedTerms(text.slice(cursor), terms, (fragment) => applyFastRulesToFragment(fragment, changes)));
  return pieces.join("");
}

/**
 * Transform locally and deterministically. Missing protected terms block the
 * operation before any output is produced.
 */
export function transformText(text, { mode = MODE_FAST, protectedTerms = [] } = {}) {
  if (typeof text !== "string") {
    throw new TypeError("Text muss eine Zeichenkette sein.");
  }
  if (countCodePoints(text) > MAX_INPUT_CHARACTERS) {
    return {
      blocked: true,
      errors: [`Der Text ist länger als ${MAX_INPUT_CHARACTERS.toLocaleString("de-DE")} Zeichen.`],
      missing_protected_terms: [],
    };
  }
  if (![MODE_FAST, MODE_SAFE].includes(mode)) {
    throw new Error("Unbekannter Bearbeitungsmodus.");
  }

  const normalizedTerms = normalizeProtectedTerms(protectedTerms);
  const missingTerms = missingProtectedTerms(text, normalizedTerms.terms);
  if (normalizedTerms.errors.length || missingTerms.length) {
    return {
      blocked: true,
      errors: normalizedTerms.errors,
      missing_protected_terms: missingTerms,
    };
  }
  if (exceedsProtectedTermMatchLimit(text, normalizedTerms.terms)) {
    return {
      blocked: true,
      errors: [protectedTermMatchLimitMessage()],
      missing_protected_terms: [],
    };
  }

  const changes = [];
  const beforeInspection = inspectText(text);
  let rewritten;
  try {
    rewritten = cleanCopyPasteArtifacts(text, normalizedTerms.terms, changes);
    if (mode === MODE_FAST) {
      rewritten = applyFastRules(rewritten, normalizedTerms.terms, changes);
    }
  } catch (error) {
    if (error instanceof ProtectedTermMatchLimitError) {
      return {
        blocked: true,
        errors: [protectedTermMatchLimitMessage()],
        missing_protected_terms: [],
      };
    }
    throw error;
  }
  return {
    blocked: false,
    provider: mode === MODE_FAST ? "browser-fast-editor" : "browser-rules",
    mode,
    original: text,
    rewritten,
    protected_terms: normalizedTerms.terms,
    modifications: changes,
    before_inspection: beforeInspection,
    after_inspection: inspectText(rewritten),
    before_statistics: textStatistics(text),
    after_statistics: textStatistics(rewritten),
  };
}

async function sha256(text) {
  if (!globalThis.crypto?.subtle) {
    return null;
  }
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** Create a downloadable audit that intentionally excludes input and output text. */
export async function createContentlessAudit(result) {
  if (result.blocked) {
    throw new Error("Für einen blockierten Vorgang gibt es keinen Prüfbericht.");
  }
  return {
    schema_version: 1,
    browser_edition_version: BROWSER_EDITION_VERSION,
    created_utc: new Date().toISOString(),
    provider: result.provider,
    mode: result.mode,
    input_sha256: await sha256(result.original),
    output_sha256: await sha256(result.rewritten),
    protected_term_count: result.protected_terms.length,
    modifications: result.modifications.map(({ kind, count }) => ({ kind, count })),
    before: {
      statistics: result.before_statistics,
      inspection: result.before_inspection,
    },
    after: {
      statistics: result.after_statistics,
      inspection: result.after_inspection,
    },
    content_included: false,
    safeguards: [
      "Browser-only deterministic processing; no language model or network request is used for entered text.",
      "This edition does not assess or alter AI provenance or statistical watermarking systems.",
      "Important texts require human review; this is not a semantic-equivalence guarantee.",
    ],
  };
}
