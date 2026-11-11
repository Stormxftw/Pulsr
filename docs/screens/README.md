# Screenshots

**`desktop-pane.png` is a capture of Hermes Desktop with live, public data** (public Discord
servers and GitHub repos; Hermes sessions show only "Untitled chat"). **Every other image is
sample data**, drawn by the plugin's
own renderer in the preview harness (`scripts/preview-server.mjs`) and cropped to the
plugin's surface. The numbers are recorded public Discord counts and a recorded GitHub
search from the test fixtures, three invented Discord servers watched by the real engine
through a scripted public API (`scripts/qa-server-status.py`, shown with the generic
Discord mark), and a scripted day of notifications watched by the real engine
(`scripts/qa-inbox-status.py`). No private data.

Regenerate them with `scripts/capture-gallery.mjs` (instructions at the top of that file).

| File | Shows |
|---|---|
| `desktop-pane.png` | The pane in Hermes Desktop 0.23.1 with live data (a capture, not the harness) |
| `pane-dark.png` | The Pulses pane at 320px |
| `notifications-dark.png` | Notification mode: a Windows-notifications pulse expanded |
| `trend-dark.png` | A Discord server expanded: online, voice and members, today against yesterday, member growth, people in voice |
| `focus-dark.png` | The pane after clicking **Focus** on the attention strip |
| `approval-dark.png` | The approval card: hosts, requests per hour, parameters |
| `builder-design-dark.png` | The builder's Design step |
