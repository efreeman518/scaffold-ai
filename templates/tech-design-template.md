# Tech Design Template - `docs/tech-design.html`

Scaffold output under `docs/`:

| File | Role |
|---|---|
| `tech-design.html` | The single canonical design document: semantic HTML, edited in place |
| `tech-design.css` | All styling, dark and light palettes |
| `tech-design.js` | Theme toggle only |
| `diagrams/diagram-{NN}.mmd` + `.svg` | Diagram source and rendered asset ([../support/tech-design-diagrams.md](../support/tech-design-diagrams.md)) |
| `TECH-DESIGN-MAINTENANCE.md` | Update rules for later edits |

Never generate a parallel `docs/tech-design.md`; README links to the HTML for architecture detail and to the maintenance file for edit rules.

Reference example: <https://github.com/efreeman518/scaffold-proof/blob/main/docs/tech-design.html>.

## What This Template Owns

- The **format**: file layout, HTML shell, TOC pattern, heading numbering, stable heading `id`s.
- The **styling and theme behavior**: `tech-design.css` and `tech-design.js`.

## What It Does NOT Own

- The diagram list. Section count and diagram inventory are **project-driven** - generate sections that the scaffolded code actually needs, named from the entity list (`.scaffold/domain-specification.yaml`), the resource list (`.scaffold/resource-implementation.yaml`), and the active design decisions (`.scaffold/DESIGN-DECISIONS.md`). Do not pad with stub sections for unused subsystems.

## Generation Rules

1. Every diagram embeds `diagrams/diagram-{NN}.svg` in a `<figure class="diagram-container">` - never an inline `mermaid` fence or runtime (see [../support/tech-design-diagrams.md](../support/tech-design-diagrams.md) section Filename Convention).
2. Section headings are numbered (`<h2 id="2-{slug}">2. {Section}</h2>`); subsections follow the same rule (`<h3 id="21-{slug}">2.1 {Subsection}</h3>`). Keep `id`s stable, since README and cross-section links (`<a href="#11-audit-strategy">`) target them.
3. Replace `{ProjectName}`, `{app}`, and other placeholders per [../ai/placeholder-tokens.md](../ai/placeholder-tokens.md).
4. Keep styling in `tech-design.css` and behavior in `tech-design.js`; the HTML carries no `<style>` block and no inline script.
5. When AI or hosted UI test lanes are generated, include durable rationale: explicit `AiServices:Provider` selection with `None` as default, selected-provider validation without endpoint/runtime inference, the optional LiveAI classification owned by [../skills/ai-integration.md](../skills/ai-integration.md), required-infrastructure false opt-outs and Docker preflight, post-preflight failures staying red with diagnostics, Uno Skia canvas bridge rationale, one cumulative startup deadline, bounded Playwright runner design, and Aspire-hosted UI URL resolution. Document env var or Aspire-resolved URL only; no fixed localhost fallback URLs in `docs/tech-design.html`. Put exact commands and pass conditions in README/test README; keep this doc as architecture/test rationale.

## HTML Shell (`docs/tech-design.html`)

Static - no CDN, no build step. It opens from the filesystem or serves as a plain static asset.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ProjectName} - Technical Design Document</title>
<link rel="stylesheet" href="tech-design.css">
</head>
<body>
<div class="doc-toolbar"><button class="theme-toggle" type="button" data-theme-toggle>Light</button></div>
<div class="container">
<h1 id="{app}---technical-design-document">{ProjectName} - Technical Design Document</h1>
<div class="callout">
<p><strong>Audience</strong>: Developers onboarding to the project</p>
</div>
<hr>
<h2 id="table-of-contents">Table of Contents</h2>
<ol>
<li><a href="#1-overview">Overview</a></li>
<!-- one <li><a href="#N-slug">Title</a></li> per numbered h2 -->
</ol>
<hr>
<h2 id="1-overview">1. Overview</h2>
<!-- ... -->
<h2 id="2-{slug}">2. {Section title}</h2>
<p>{Intro.}</p>
<figure class="diagram-container">
<img src="diagrams/diagram-01.svg" alt="2. {Diagram title}">
</figure>
<!-- Repeat per project-driven section. -->
</div>
<script src="tech-design.js"></script>
</body>
</html>
```

## `docs/tech-design.css`

GitHub palette, dark by default; `:root[data-theme="light"]` overrides the same tokens.

```css
:root, :root[data-theme="dark"] {
  --bg: #0d1117; --surface: #161b22; --border: #30363d; --text: #e6edf3;
  --text-muted: #8b949e; --accent: #58a6ff; --purple: #bc8cff; --cyan: #79c0ff;
}
:root[data-theme="light"] {
  --bg: #ffffff; --surface: #f6f8fa; --border: #d0d7de; --text: #24292f;
  --text-muted: #57606a; --accent: #0969da; --purple: #8250df; --cyan: #0550ae;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.6; }
.container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
h1 { font-size: 2.2rem; border-bottom: 2px solid var(--accent); padding-bottom: 0.5rem; margin-bottom: 1rem; }
h2 { font-size: 1.7rem; color: var(--accent); margin: 2.5rem 0 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4rem; }
h3 { font-size: 1.3rem; color: var(--purple); margin: 1.5rem 0 0.8rem; }
h4 { font-size: 1.1rem; color: var(--cyan); margin: 1.2rem 0 0.6rem; }
p, li { margin-bottom: 0.5rem; }
ul, ol { padding-left: 1.5rem; margin-bottom: 1rem; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code { background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 2px 6px; font-size: 0.9em; color: var(--cyan); }
pre { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; overflow-x: auto; margin: 1rem 0; }
pre code { border: none; padding: 0; background: transparent; }
table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
th { background: var(--surface); color: var(--accent); text-align: left; padding: 0.6rem 1rem; border: 1px solid var(--border); font-weight: 600; }
td { padding: 0.5rem 1rem; border: 1px solid var(--border); vertical-align: top; }
hr { border: 0; border-top: 1px solid var(--border); margin: 1.5rem 0; }
.diagram-container { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin: 1.5rem 0; overflow-x: auto; }
.diagram-container img { display: block; margin: 0 auto; max-width: 100%; height: auto; }
.callout { background: rgba(88,166,255,0.08); border-left: 3px solid var(--accent); padding: 0.8rem 1rem; border-radius: 0 8px 8px 0; margin: 1rem 0; }
.callout p:last-child { margin-bottom: 0; }
.doc-toolbar { position: sticky; top: 0; z-index: 10; display: flex; justify-content: flex-end; padding: 0.75rem 2rem 0; background: linear-gradient(var(--bg), rgba(0,0,0,0)); }
.theme-toggle { border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); padding: 0.35rem 0.7rem; font: inherit; cursor: pointer; }
.theme-toggle:hover { border-color: var(--accent); }
@media (max-width: 768px) { .container { padding: 1rem; } }
```

## `docs/tech-design.js`

The OS preference picks the first theme; the toggle persists the choice.

```js
(function () {
  const root = document.documentElement;
  const button = document.querySelector('[data-theme-toggle]');
  const key = '{app}-tech-design-theme';
  const preferred = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  setTheme(localStorage.getItem(key) || preferred);
  button?.addEventListener('click', () => setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark'));

  function setTheme(theme) {
    root.dataset.theme = theme;
    localStorage.setItem(key, theme);
    if (button) button.textContent = theme === 'dark' ? 'Light' : 'Dark';
  }
})();
```

## `docs/TECH-DESIGN-MAINTENANCE.md`

Generate this file so later edits keep the layout without the instruction set loaded:

- `tech-design.html` is the canonical design document; never regenerate it from Markdown or add a parallel `tech-design.md`.
- Edit it directly when code, architecture, routes, workflows, tests, or deployment topology change; patch only the affected sections.
- Styling stays in `tech-design.css`, theme behavior in `tech-design.js`.
- Diagrams are `diagrams/diagram-{NN}.svg`, each rendered from its sibling `.mmd`; edit the source and re-render, never hand-edit an SVG.
- Preserve heading `id`s; README links and external references target them.
- Prefer semantic HTML: headings, tables, lists, `figure`, `img`, `code`, `pre`.
- After edits, re-render changed diagrams and check for stale `tech-design.md` links and missing diagram paths. Generation copies in the commands from the Render Gate and Final Doc Validation sections of [../support/tech-design-diagrams.md](../support/tech-design-diagrams.md).

## When to Generate

`docs/tech-design.html` is a Phase 5d deliverable. Generate it after `test-templates-quality` is in place and the scaffold satisfies the applicable [final acceptance criteria](../support/final-scaffold-checklist.md). The doc reflects the *shipped* topology - sections whose backing code is not generated are dropped, not stubbed.

Generation order per session:

1. Decide the section list from the actual scaffold output (entities, hosts, integrations, design decisions).
2. Write each `diagrams/diagram-{NN}.mmd` source per section need.
3. Run the **render gate** (see [../support/tech-design-diagrams.md](../support/tech-design-diagrams.md) section Render Gate) to produce `.svg` siblings.
4. Write `docs/tech-design.html`, `tech-design.css`, `tech-design.js`, and `TECH-DESIGN-MAINTENANCE.md` from the shapes above.
5. Run the **final-doc validation** ([../support/tech-design-diagrams.md](../support/tech-design-diagrams.md) section Final Doc Validation), then open the file from disk to confirm the diagrams load and the theme toggle works offline.

Later changes edit `docs/tech-design.html` in place, patching only the affected sections.
