# WarrantOS as a Claude Code plugin

This repository ships a `.claude-plugin/plugin.json` manifest so the claim
gate can be installed as a Claude Code plugin rather than wired by hand into
`settings.json`. This document covers install, what the two bundled hooks do,
how to turn the plugin off for a single project, and where it stands on
marketplace distribution.

## Install

### Try it locally, without installing

From a checkout of this repository:

```bash
claude --plugin-dir /path/to/claude-provenance
```

This loads the plugin for the current session only. Run `/reload-plugins`
after editing any file under `.claude-plugin/`, `hooks/`, or `commands/` to
pick up changes without restarting.

### Install from this repository's marketplace listing

The repository also ships `.claude-plugin/marketplace.json`, which registers
a marketplace named `claude-provenance` containing one plugin entry, also
named `claude-provenance` in that file. Add the marketplace and install from
it:

```bash
claude plugin marketplace add jvega017/claude-provenance
claude plugin install claude-provenance@claude-provenance
```

Note the naming split: `plugin.json`'s internal `name` field is `warrantos`
(it governs the skill/command namespace, so the bundled command is invoked as
`/warrant`), but the marketplace entry in `marketplace.json` still lists the
plugin as `claude-provenance`. Per the Claude Code plugin schema, the
marketplace entry name is what `claude plugin install`, `enabledPlugins`, and
`/plugin` use, so install and enable/disable commands reference
`claude-provenance@claude-provenance`, not `warrantos@claude-provenance`.
Reconciling this (for example, renaming the marketplace entry to `warrantos`
to match) is a follow-up item, not yet done.

## What the bundled hooks do

Two hooks are wired in `plugin.json`, both pointing at scripts under
`warrantos/hooks/` via `${CLAUDE_PLUGIN_ROOT}`:

| Hook script | Event | What it does |
|---|---|---|
| `provenance_check.py` | `PostToolUse` (matcher `Write\|Edit`) | Runs immediately after Claude writes or edits a file, checking the changed content for unsourced factual claims and AI scaffold residue. |
| `claude_code_verify_hook.py` | `Stop` | Runs when Claude finishes a turn. Reads the most recent WarrantOS run under `.warrant/runs/`, and if it finds unverified load-bearing claims that triggered a `HOLD`, blocks the turn from ending (hook exit code 2) and hands the list of unverified claims back to Claude so they can be sourced or explicitly flagged before the session moves on. It is loop-safe: it will not re-block on the same unresolved hand-back. |

Both hooks are stdlib-only Python and make no network calls on their own.
Neither hook requires an `ANTHROPIC_API_KEY`; the verification the `Stop`
hook asks for is performed by the session's own model, not a separate
grader.

## Slash command: `/warrant`

`commands/warrant.md` adds a `/warrant [file]` command. With no argument it
targets the most recently written or edited file in the session; with an
argument it targets that path. It runs `warrantos check --profile
brief-light --json` and reports the verdict, the claim counts, every
offending sentence with its salience score, and the run's output directory.

## Disable the plugin for one project

To turn the plugin off in a single project without uninstalling it
elsewhere:

```bash
claude plugin disable claude-provenance@claude-provenance --scope project
```

This writes the disabled state to that project's `.claude/settings.json`
under `enabledPlugins`, which takes precedence over the plugin's own
`defaultEnabled` value and persists across updates. Use `--scope local` to
write to the gitignored `.claude/settings.local.json` instead if the
disablement should not be checked into version control. Re-enable with
`claude plugin enable claude-provenance@claude-provenance --scope <scope>`.

## Validate the manifest

```bash
python -c "import json; json.load(open('.claude-plugin/plugin.json'))"
claude plugin validate .
```

The Python check confirms the file is syntactically valid JSON. `claude
plugin validate` (run from the plugin root) additionally checks the manifest
against the Claude Code schema, and validates skill/command frontmatter and
`hooks/hooks.json` syntax; running it requires a local Claude Code
installation and was not exercised as part of this change.

## Marketplace distribution status

Honest state as of this writing: **this plugin is not yet listed in any
Claude Code plugin marketplace beyond the repository's own
`marketplace.json`.** No submission has been made. The candidate targets for
a future submission are:

1. **`anthropics/claude-plugins-official`** partner track: Anthropic's
   curated marketplace. There is no application process; Anthropic decides
   inclusion at its discretion.
2. **`claudemarketplaces.com`**: a third-party community marketplace listing
   site.
3. **`tonsofskills/ccpi`**: a community-maintained plugin/skill index on
   GitHub.
4. **`aitmpl.com`**: a third-party template and plugin directory.

Submitting to Anthropic's own community marketplace
(`anthropics/claude-plugins-community`) via the in-app submission form
(`claude.ai/admin-settings/directory/submissions/plugins/new` or
`platform.claude.com/plugins/submit`) is also an option and was not on the
original list of four targets above, but is worth noting as the
first-party community route.
