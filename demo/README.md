# Demo assets

This directory holds the source material for a terminal recording of
WarrantOS's two zero-setup commands: `warrantos demo` (the bundled honest
demo, a real BLOCK verdict) and `warrantos slop docs` (the AI-scaffold-residue
scanner). Nothing here is fabricated: every line of terminal output was
captured by actually running the CLI in this repository. See
`demo/captures.txt` for the raw transcript.

## Files

- `captures.txt`: raw, unedited output of three real CLI invocations
  (`warrantos demo`, `warrantos slop README.md docs`,
  `warrantos slop --badge README.md`), each preceded by the exact command
  line. This is the source of truth every other asset in this directory is
  built from.
- `demo.cast`: a hand-built [asciinema v2](https://docs.asciinema.org/manual/asciicast/v2/)
  recording that replays the same two commands (`warrantos demo`, then
  `warrantos slop docs`) with a typed prompt and the real output revealed
  line by line. Runtime is about 24 seconds.
- `demo.tape`: a [VHS](https://github.com/charmbracelet/vhs) tape script
  that renders the same two-command scene to a GIF.
- This file.

## Playing the asciinema cast

No extra tooling is required beyond `asciinema` itself:

```bash
# Play locally
asciinema play demo/demo.cast

# Or upload it and get a shareable link/embed
asciinema upload demo/demo.cast
```

`demo.cast` is a plain-text v2 asciicast: a JSON header line followed by one
`[time, "o", text]` event per line. It was authored by hand from the
transcript in `captures.txt`, not recorded live, because `asciinema` is not
installed in the environment that produced this directory. Every line has
been validated as parseable JSON (see the file's own header/body split); the
content matches the real captured command output verbatim, only reformatted
into typed-then-revealed events with plausible typing and processing pauses.

## Rendering the GIF

`demo.gif` has **not been rendered**. `vhs` (and its `ttyd`/`ffmpeg`
dependencies) is not installed in this environment, so `demo.tape` has not
been executed here. To produce the GIF once `vhs` is available:

```bash
# from the repo root, with `warrantos` on PATH (e.g. pip install -e .)
vhs demo/demo.tape
```

This runs the two commands live in a real shell and writes `demo/demo.gif`.
Because it executes the actual CLI rather than replaying a transcript, its
output will reflect whatever run id and file counts are current at render
time, not the exact `run_c6421e797c88` / `2.7/10` figures frozen in
`captures.txt` and `demo.cast`.

## Where the GIF belongs

Once rendered, `demo.gif` is destined for the **"Ten seconds"** section near
the top of `README.md` (currently a static fenced code block showing trimmed
`warrantos demo` output). The GIF should sit alongside or replace that block
as a visual demonstration of the same real command; it is not wired into
`README.md` by this change; embedding it is a separate follow-up once the
render exists and has been reviewed.
