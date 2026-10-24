// Inlines the standalone walk-through build into one HTML file: dist-walk/touchspace-walk.html.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

const html = readFileSync("dist-walk/standalone/walk.html", "utf8");
const base = "dist-walk/standalone";
const jsSrc = html.match(/<script[^>]*src="([^"]+)"[^>]*><\/script>/)[1];
const cssHref = html.match(/<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>/)[1];
const js = readFileSync(join(base, jsSrc), "utf8").replace(/<\/script/gi, "<\\/script");
const css = readFileSync(join(base, cssHref), "utf8");

// The app's dark palette is a .dark class. Repeat it for the viewer's system theme and an
// explicit data-theme choice, so the page is right even before its script runs.
const darkVars = css.match(/\.dark\{([^}]*)\}/)?.[1];
if (!darkVars) throw new Error("Couldn't find the .dark palette in the built CSS.");
const themeCss =
  `@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){${darkVars}}}` + `:root[data-theme="dark"]{${darkVars}}`;

const page = `<title>TouchSpace Walk-through</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&display=swap" rel="stylesheet">
<style>${css}${themeCss}</style>
<div id="root"></div>
<script type="module">${js}</script>
`;
const out = join(dirname(base), "touchspace-walk.html");
writeFileSync(out, page);
console.log(`${out}: ${(page.length / 1024).toFixed(0)} KB`);
