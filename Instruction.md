Set up project docs. Exact order, no deviation.

VAULT = the root of the currently open repository. Do not ask for a path.
Every generated file is written inside it:
- ARCHITECTURE.md  -> <repo-root>/ARCHITECTURE.md
- CLAUDE.md        -> <repo-root>/CLAUDE.md
- component notes  -> <repo-root>/docs/components/<Name>.md
Create docs/components/ if missing. Overwrite files of the same name in place.
No -v2, -new, or dated variants. Never write outside the repo root.

## 1. READ — only these
- manifest: package.json | go.mod | pyproject.toml | Cargo.toml
- tree -L 3 -I 'node_modules|vendor|dist|build|.git'
  if tree is missing:
  find . -maxdepth 3 -not -path '*/node_modules/*' -not -path '*/.git/*'
- entry points declared in the manifest, max 3 files
- the import/require block at the top of those entry files only —
  stop reading at the first non-import statement
- README, if present
No implementation bodies. No grep. No file-by-file exploration.

## 2. ARCHITECTURE.md — repo root, <=120 lines
Frontmatter: tags: [architecture, <repo-name>]
1. Stack — languages, frameworks, key libs. <=5 lines.
2. Directory map — table `path | what lives there`. 2 levels.
3. Diagram — Mermaid flowchart TD, <=12 nodes, component boundaries only.
   Node label = component note filename without the .md. Exact match.
4. Component index — one [[Wikilink]] per diagram node.
5. Entry points — dev and prod, with paths.
6. Conventions — naming, file placement, error handling. Observed only.
7. Where things go — "to add a new X, touch these files." 3-5 tasks.

## 3. Component notes — one per diagram node, docs/components/, <=6 lines each
Filename = diagram node label + .md
Frontmatter: tags: [component, <repo-name>]
- Path: <dir or file>
- Role: <one line>
- Talks to: [[A]], [[B]]   # mirror the diagram edges exactly; edges come from
                           # the import blocks read in step 1, nothing else
- Back: [[ARCHITECTURE]]
Obsidian resolves [[links]] by filename across folders, so the graph renders
from docs/components/. The Mermaid block is not graphed.

## 4. CLAUDE.md — repo root, <=40 lines
- build, test, lint commands as exact strings
- rules you'd otherwise break (e.g. "pnpm not npm", "never edit /generated")
- 3 files worth reading first, with paths
- the line: Architecture: see ARCHITECTURE.md — read before structural changes
Exclude: what the project does, linter-enforced style, task workflows,
anything inferred rather than observed.

## Rules
- Every claim cites a real path relative to repo root.
  Unsure -> "TODO: verify". Never guess.
- Bullets, tables, diagram, frontmatter only. No prose.
- Mermaid only, never .canvas.
- Write the files, then stop. No summary.
