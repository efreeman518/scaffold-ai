# Tech Design Diagrams - Source-Plus-SVG, Render Gate, and Validation

Canonical diagram rules for `docs/tech-design.html`, the single canonical design document (no parallel `docs/tech-design.md`). The file layout, HTML shell, styling, and theme script live in [../templates/tech-design-template.md](../templates/tech-design-template.md). Reference shape: <https://github.com/efreeman518/scaffold-proof/blob/main/docs/tech-design.html>.

The scaffold owns the **diagram format**, not the diagram list. Which diagrams to include is a per-project decision driven by `.scaffold/domain-specification.yaml`, `.scaffold/resource-implementation.yaml`, and what the app actually generates.

## Why Source-Plus-SVG

A live Mermaid runtime needs a CDN, and GitHub's renderer rejects variants the local Mermaid CLI accepts (C4, `block-beta`, complex `erDiagram`, `classDef` styling). Committing the `.mmd` source and a rendered `.svg` renders deterministically offline and keeps the source editable.

## Scope

| Applies | Does not apply |
|---|---|
| `docs/tech-design.html` and any peer **GitHub-rendered** architecture/topology docs under `docs/` | Scaffold-internal artifacts under `.scaffold/` (e.g. `DESIGN-DECISIONS.md`, `implementation-plan.md`). Inline `mermaid` fences are fine there - those are working artifacts, not GitHub-rendered docs. |

If a diagram source is a basic `flowchart` / `sequenceDiagram` / `stateDiagram` with **no** `classDef` styling and **no** `block-beta` / C4 / `classDiagram-v2`, an inline fence in a peer Markdown doc is acceptable. When in doubt, render to SVG.

## Source-Plus-Rendered Pattern

1. **Editable source** - `docs/diagrams/diagram-{NN}.mmd`, one diagram per file.
2. **Rendered asset** - the sibling `docs/diagrams/diagram-{NN}.svg`, checked in.
3. **`docs/tech-design.html`** embeds the SVG:

   ```html
   <figure class="diagram-container">
   <img src="diagrams/diagram-{NN}.svg" alt="{N.n} {Title}">
   </figure>
   ```

4. **Do not** include a live Mermaid runtime in generated HTML:
   - no `mermaid@...` CDN `<script>`
   - no `class="mermaid"` blocks
   - no `mermaid.initialize(...)` call

The reference app ships its SVGs without `.mmd` sources. In a doc like that, recreate the source for a diagram the first time that diagram changes; never hand-edit a rendered SVG.

## Filename Convention

`docs/diagrams/diagram-{NN}.{mmd,svg}` where `{NN}` is a zero-padded two-digit ordinal in document order. The number is for sort stability across `Get-ChildItem` and PR diffs - not a fixed registry; the `alt` text carries the section number and title. Keep a published number when a section is dropped, so existing references stay valid.

## Render Gate (scaffold time)

Run after creating or editing any `.mmd` file. Fails fast on the first diagram that does not render.

```powershell
powershell -NoProfile -Command '& {
  $fail = @()
  Get-ChildItem "docs\diagrams\*.mmd" | Sort-Object Name | ForEach-Object {
    $out = [System.IO.Path]::ChangeExtension($_.FullName, ".svg")
    npx -y "@mermaid-js/mermaid-cli@<latest-stable>" -i $_.FullName -o $out -t dark -b transparent --quiet
    if ($LASTEXITCODE -ne 0) { $fail += $_.Name }
  }
  if ($fail.Count -eq 0) { "all ok" } else { $fail; exit 1 }
}'
```

Resolve `<latest-stable>` when generating the project and record it in the project's npm lockfile so repeated renders are deterministic. A transparent background lets the diagram sit on the `.diagram-container` surface in both themes.

## Final Doc Validation

Run before declaring the tech-design docs done. All checks must exit clean.

```powershell
# 1. No live Mermaid runtime and no stale Markdown-twin links (no hits expected)
rg -n -e 'class="mermaid"' -e 'mermaid\.initialize' -e 'mermaid@' docs\tech-design.html
rg -n '[(/"]tech-design\.md' README.md docs

# 2. Whitespace/CRLF damage on the SVG payload
git diff --check

# 3. Every SVG reference resolves on disk
powershell -NoProfile -Command '& {
  $bad=@(); Select-String -Path docs\tech-design.html -Pattern "diagrams/[\w-]+\.svg" -AllMatches |
    ForEach-Object { $_.Matches } | ForEach-Object {
      $rel="docs/" + $_.Value
      if (-not (Test-Path $rel)) { $bad += $_.Value }
    }
  if ($bad.Count -eq 0) { "all svg refs resolve" } else { $bad; exit 1 }
}'
```

Also verify every TOC and cross-section `href="#..."` matches an `id` in the body.

## Expected Result

- Each `.mmd` source remains editable; rerunning the render gate regenerates its `.svg` deterministically.
- `docs/tech-design.html` opens directly from the filesystem, loads every diagram, and switches theme offline - no external CDN.
- A diagram edit requires one `.mmd` change + one render-gate run.
