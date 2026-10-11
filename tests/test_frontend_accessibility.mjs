import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (file) => fs.readFileSync(path.join(ROOT, file), "utf8");

function sourceFiles(dir) {
  const out = [];
  for (const entry of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
    if (entry.isDirectory()) out.push(...sourceFiles(`${dir}/${entry.name}`));
    else if (entry.name.endsWith(".tsx")) out.push(read(`${dir}/${entry.name}`));
  }
  return out;
}

function contrast(hexA, hexB) {
  const luminance = (hex) => {
    const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
    const linear = channels.map((value) =>
      value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
    );
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  };
  const [light, dark] = [luminance(hexA), luminance(hexB)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}

test("Explore uses separate responsive search refs and avoids nested card controls", () => {
  const source = read("src/app/explore/ExploreClient.tsx");
  assert.match(source, /mobileSearchInputRef/);
  assert.match(source, /desktopSearchInputRef/);
  assert.doesNotMatch(source, /<button[^>]*>\s*<StationCard/);
  assert.match(source, /role="group"[\s\S]*event\.target\.closest\("a,button/);
});

test("primary button text meets WCAG AA in every configured state", () => {
  const source = read("src/components/Button.tsx");
  assert.match(source, /bg-coral-600 text-ink-900/);
  for (const background of ["#F08080", "#D86A6A", "#FBC4AB"]) {
    assert.ok(contrast(background, "#1F1B1A") >= 4.5, `${background} contrast is below 4.5:1`);
  }
});

test("modal primitives expose labels and implement focus containment", () => {
  const sheet = read("src/components/BottomSheet.tsx");
  const modal = read("src/components/Modal.tsx");
  assert.match(sheet, /aria-modal="true"/);
  assert.match(sheet, /aria-label=\{!title \? ariaLabel : undefined\}/);
  assert.match(sheet, /e\.key !== "Tab"/);
  assert.match(modal, /aria-labelledby=\{title \? titleId : undefined\}/);
  assert.match(modal, /previousFocus\?\.focus\(\)/);
});

test("no anchor wraps a button, anywhere in the app tree", () => {
  for (const s of sourceFiles("src")) {
    assert.doesNotMatch(
      s,
      /<Link[^>]*>\s*<Button/,
      "nested interactive elements: use <Button href=...> instead of <Link><Button>"
    );
    assert.doesNotMatch(s, /<\/Button>\s*<\/Link>/);
  }
});

test("Button can navigate without nesting a button inside an anchor", () => {
  const button = read("src/components/Button.tsx");
  assert.match(button, /href\?: string;/);
  assert.match(button, /<Link[\s\S]*href=\{href\}/);
});

test("every coral-filled control uses ink text, never white", () => {
  for (const s of sourceFiles("src")) {
    for (const line of s.split("\n")) {
      if (/bg-coral-(300|400|600|700)\b/.test(line)) {
        assert.doesNotMatch(
          line,
          /text-white/,
          `coral background with white text fails WCAG AA: ${line.trim()}`
        );
      }
    }
  }
});

test("map failures are surfaced and map popups carry an accessible name", () => {
  const map = read("src/components/MapLibreMap.tsx");
  assert.match(map, /map\.on\("error"/);
  assert.match(map, /setMapError\(true\)/);
  assert.match(map, /t\("errors\.map\.title"\)/);
  assert.match(map, /setAttribute\("aria-label"/);
  // A transient tile error must not blank out an otherwise working map.
  assert.match(map, /if \(!map\.isStyleLoaded\(\)\) setMapError\(true\)/);
});

test("skip link, main landmark target and nav active state are wired", () => {
  const header = read("src/components/SiteHeader.tsx");
  const layout = read("src/app/layout.tsx");
  assert.match(header, /href="#main"/);
  assert.match(header, /aria-current=\{active \? "page" : undefined\}/);
  assert.match(layout, /<main id="main"/);
});

test("heading levels stay ordered: one h1 per page and no level skips", () => {
  const explore = read("src/app/explore/ExploreClient.tsx");
  const sheet = read("src/components/StationPreviewSheet.tsx");
  const footer = read("src/components/SiteFooter.tsx");
  assert.match(explore, /<h1 className="sr-only">/);
  assert.doesNotMatch(explore, /<h3/);
  assert.doesNotMatch(sheet, /<h3/);
  assert.doesNotMatch(footer, /<h4/);
});
