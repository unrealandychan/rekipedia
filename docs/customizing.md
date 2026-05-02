# Customizing Your Wiki

rekipedia generates pages automatically, but you stay in control.
Every generated page is plain Markdown — you can edit, pin, delete, or add pages freely.

---

## How pages are generated

When you run `rekipedia scan`, the tool writes Markdown files into `.rekipedia/wiki/`:

```
.rekipedia/wiki/
├── index.md              ← repo overview (generated)
├── architecture.md       ← module/component map (generated)
├── core-modules.md       ← key classes & functions (generated)
├── build-and-deploy.md   ← build commands & deploy (generated)
└── testing-strategy.md   ← test approach (generated)
```

All pages are re-generated from the SQLite store (`store.db`) on every `scan` or `update`.
**Your edits will be overwritten** unless you protect them (see below).

---

## Option 1 — Pin a page (never overwrite)

Add a frontmatter `pin: true` block at the top of any page:

```markdown
---
pin: true
---

# Auth Flow

My hand-written explanation that rekipedia should never touch...
```

rekipedia will skip pinned pages during generation and leave them exactly as you wrote them.

---

## Option 2 — Add a custom page

Create any `.md` file inside `.rekipedia/wiki/` that does **not** match a generated slug.
rekipedia will never delete files it did not create.

```
.rekipedia/wiki/
├── onboarding.md        ← your custom page, untouched by scans
├── adr-001-postgres.md  ← architecture decision record
└── runbook-deploy.md    ← ops runbook
```

---

## Option 3 — Edit and re-pin after a scan

1. Run `rekipedia scan` to get the latest generated version.
2. Open the page and make your edits.
3. Add `pin: true` to the frontmatter.

From that point forward, `scan` and `update` will preserve your version.

---

## Option 4 — Override the prompt for a page

You can customize *how* rekipedia generates a specific page by adding a
`prompt_overrides` key to `.rekipedia/config.yml` (keys are page slugs):

```yaml
# .rekipedia/config.yml
prompt_overrides:
  architecture: |
    Focus on the event-driven parts of the system only.
    Ignore the legacy REST layer.
  core-modules: |
    Only document public-facing classes.
    Skip internal helpers.
```

The key must match one of the five standard page slugs: `index`, `architecture`,
`core-modules`, `build-and-deploy`, `testing-strategy`.
This feature is **live** as of v0.2.0.

---

## Option 5 — Exclude topics entirely

Add slugs to the `exclude_pages` list in `config.yml` to prevent certain pages from
being generated at all:

```yaml
# .rekipedia/config.yml
exclude_pages:
  - testing-strategy   # we maintain test docs by hand
```

This feature is **live** as of v0.2.0.

---

## Option 6 — Change the writing style / language

The `llm.system_prompt` key lets you inject a global instruction into every page generation:

```yaml
llm:
  model: gpt-5.5
  system_prompt: |
    You are a senior engineer writing for a junior audience.
    Use simple language. Avoid jargon. Add a TL;DR at the top of every page.
    Write in French.
```

---

## Workflow recommendation

| Situation | What to do |
|---|---|
| Page is mostly right, small edits needed | Edit + `pin: true` |
| Page is wrong for your context | Add a `prompt_overrides` entry in `config.yml`, re-run `scan` |
| Topic should never appear | Add to `exclude_pages` |
| You want to write a page from scratch | Create a new `.md` file, don't use a generated slug |
| You want all pages in a different style | Set `llm.system_prompt` in `config.yml` |

---

## Resetting a pinned page

To let rekipedia regenerate a pinned page, remove the `pin: true` line and run `rekipedia scan`.
