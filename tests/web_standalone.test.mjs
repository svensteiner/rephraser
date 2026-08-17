import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

class FakeElement {
  constructor(tagName = "DIV") {
    this.tagName = tagName.toUpperCase();
    this.value = "";
    this.textContent = "";
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.readOnly = false;
    this.checked = false;
    this.files = [];
    this.children = [];
    this.listeners = new Map();
  }

  get firstChild() {
    return this.children[0] ?? null;
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  async emit(type, event = {}) {
    const baseEvent = { preventDefault() {}, ...event };
    await Promise.all((this.listeners.get(type) ?? []).map((listener) => listener(baseEvent)));
  }

  append(...nodes) {
    this.children.push(...nodes);
  }

  removeChild(node) {
    const index = this.children.indexOf(node);
    if (index >= 0) {
      this.children.splice(index, 1);
    }
    return node;
  }

  focus() {
    this.focused = true;
  }

  select() {
    this.selected = true;
  }

  scrollIntoView() {}

  click() {
    return this.emit("click");
  }

  remove() {}
}

function createBrowserHarness() {
  const ids = [
    "source-text", "protected-terms", "file-input", "paste-button", "transform-button",
    "status-message", "error-message", "character-count", "mode-help", "result-section",
    "result-heading", "original-preview", "result-text", "before-stats", "after-stats",
    "change-list", "character-findings", "copy-button", "save-button", "audit-button",
    "clear-button", "review-confirmation", "review-checkbox",
  ];
  const elements = Object.fromEntries(ids.map((id) => [id, new FakeElement(id.includes("text") || id.includes("terms") ? "textarea" : "div")]));
  const safe = new FakeElement("input");
  safe.value = "safe";
  safe.checked = true;
  const fast = new FakeElement("input");
  fast.value = "fast";
  const modeInputs = [safe, fast];
  const frames = [];
  const timers = [];
  const documentListeners = new Map();
  const document = {
    body: new FakeElement("body"),
    querySelector(selector) {
      if (selector === "input[name='mode']:checked") {
        return modeInputs.find((input) => input.checked);
      }
      if (selector.startsWith("#")) {
        return elements[selector.slice(1)] ?? null;
      }
      return null;
    },
    querySelectorAll(selector) {
      return selector === "input[name='mode']" ? modeInputs : [];
    },
    createElement(tagName) {
      return new FakeElement(tagName);
    },
    addEventListener(type, listener) {
      const listeners = documentListeners.get(type) ?? [];
      listeners.push(listener);
      documentListeners.set(type, listeners);
    },
    execCommand() {
      return true;
    },
  };
  const window = {
    requestAnimationFrame(callback) {
      frames.push(callback);
      return frames.length;
    },
    matchMedia() {
      return { matches: true };
    },
    setTimeout(callback) {
      timers.push(callback);
      return timers.length;
    },
    confirm() {
      return true;
    },
  };
  return { document, elements, frames, modeInputs, timers, window };
}

async function withBrowserHarness(callback) {
  const harness = createBrowserHarness();
  const names = ["document", "window", "navigator"];
  const descriptors = new Map(names.map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  Object.defineProperties(globalThis, {
    document: { configurable: true, writable: true, value: harness.document },
    window: { configurable: true, writable: true, value: harness.window },
    navigator: { configurable: true, writable: true, value: {} },
  });
  try {
    const appUrl = new URL(`../web/app.js?browser-test=${Date.now()}-${Math.random()}`, import.meta.url);
    await import(appUrl.href);
    await callback(harness);
  } finally {
    for (const name of names) {
      const descriptor = descriptors.get(name);
      if (descriptor) {
        Object.defineProperty(globalThis, name, descriptor);
      } else {
        delete globalThis[name];
      }
    }
  }
}

async function completeQueuedFrame(harness, run) {
  await Promise.resolve();
  assert.equal(harness.frames.length, 1);
  harness.frames.shift()(0);
  await run;
}

test("offline browser file contains one syntactically valid, self-contained script", async () => {
  const page = await readFile(new URL("../web/TextVerbessern-Browser.html", import.meta.url), "utf8");
  const scripts = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)];

  assert.equal(scripts.length, 1);
  assert.doesNotThrow(() => new Function(scripts[0][1]));
  assert.match(page, /connect-src 'none'/);
  assert.ok(page.indexOf("<script>") > page.indexOf("</main>"));
  assert.ok(page.indexOf("<script>") < page.indexOf("</body>"));
  assert.doesNotMatch(page, /src="\.\/app\.js"/);
});

test("browser defaults to safe cleanup and only unlocks copy after review for linguistic changes", { concurrency: false }, async () => {
  await withBrowserHarness(async ({ elements, frames }) => {
    elements["source-text"].value = "A\u200BB";
    const safeRun = elements["transform-button"].emit("click");
    await completeQueuedFrame({ elements, frames }, safeRun);

    assert.equal(elements["result-text"].value, "AB");
    assert.equal(elements["review-confirmation"].hidden, true);
    assert.equal(elements["copy-button"].disabled, false);
  });

  await withBrowserHarness(async ({ elements, frames, modeInputs }) => {
    modeInputs[0].checked = false;
    modeInputs[1].checked = true;
    await modeInputs[1].emit("change");
    elements["source-text"].value = "We would like to better understand the report.";
    const fastRun = elements["transform-button"].emit("click");
    await completeQueuedFrame({ elements, frames }, fastRun);

    assert.equal(elements["review-confirmation"].hidden, false);
    assert.equal(elements["copy-button"].disabled, true);
    elements["review-checkbox"].checked = true;
    await elements["review-checkbox"].emit("change");
    assert.equal(elements["copy-button"].disabled, false);
  });
});

test("browser transformation completes when animation frames are paused", { concurrency: false }, async () => {
  await withBrowserHarness(async ({ elements, timers, window }) => {
    window.requestAnimationFrame = () => 0;
    elements["source-text"].value = "A\u200BB";
    const run = elements["transform-button"].emit("click");

    await Promise.resolve();
    assert.equal(timers.length, 1);
    timers.shift()();
    await run;

    assert.equal(elements["result-text"].value, "AB");
    assert.equal(elements["copy-button"].disabled, false);
  });
});

test("browser discards rAF results when source, mode, or protected terms change", { concurrency: false }, async () => {
  const changes = [
    async ({ elements }) => {
      elements["source-text"].value = "Changed source";
      await elements["source-text"].emit("input");
    },
    async ({ modeInputs }) => {
      modeInputs[0].checked = false;
      modeInputs[1].checked = true;
      await modeInputs[1].emit("change");
    },
    async ({ elements }) => {
      elements["protected-terms"].value = "Project Aurora";
      await elements["protected-terms"].emit("input");
    },
  ];

  for (const change of changes) {
    await withBrowserHarness(async (harness) => {
      harness.elements["source-text"].value = "We would like to better understand the report.";
      const run = harness.elements["transform-button"].emit("click");
      await Promise.resolve();
      assert.equal(harness.elements["source-text"].readOnly, true);
      assert.equal(harness.modeInputs[0].disabled, true);
      assert.equal(harness.elements["clear-button"].disabled, true);

      await change(harness);
      await completeQueuedFrame(harness, run);

      assert.equal(harness.elements["result-section"].hidden, true);
      assert.equal(harness.elements["result-text"].value, "");
      assert.equal(harness.elements["copy-button"].disabled, true);
      assert.match(harness.elements["status-message"].textContent, /verworfen/);
      assert.equal(harness.elements["source-text"].readOnly, false);
      assert.equal(harness.modeInputs[0].disabled, false);
    });
  }
});
