import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

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
