# demo/demo.tape
#
# VHS tape script for the WarrantOS honest-demo GIF.
# Render with (from the repo root, `warrantos` on PATH, e.g. `pip install -e .`):
#   vhs demo/demo.tape
# Requires the vhs CLI (https://github.com/charmbracelet/vhs) and its ttyd/ffmpeg
# dependencies. vhs is NOT installed in this build environment, so this tape
# has not been executed here: it runs the two real commands live (see
# demo/captures.txt for the transcript captured by hand instead). See
# demo/README.md for render instructions.

Output demo/demo.gif

Set Shell "bash"
Set FontSize 16
Set FontFamily "JetBrains Mono"
Set Width 1000
Set Height 520
Set Padding 20
Set Theme "Dracula"
Set TypingSpeed 60ms

# Scene 1: the bundled honest demo (real BLOCK verdict, zero setup)
Type "warrantos demo"
Sleep 500ms
Enter
Sleep 3s

# Give the viewer time to read the verdict before the next command
Sleep 3s

# Scene 2: scan the docs/ tree for AI scaffold residue
Type "warrantos slop docs"
Sleep 500ms
Enter
Sleep 2s

# Hold on the SLOP SCORE table
Sleep 3s
