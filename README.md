# User Manual

![](<.gitbook/assets/new-user-manual-cover-2 (1).png>)

## About this fork: the manual now lives in the xLights wiki

This GitBook manual was moved, chapter by chapter, into the [xLights wiki](https://github.com/xLightsSequencer/xLights/wiki) in November 2026. Every page was rewritten for xLights 2026.19-2026.20 from the source and given fresh screenshots. The wiki is now the maintained copy, and this repository is no longer updated.

How the wiki is kept current:

- **Watcher:** the *xLights wiki watch* workflow (`.github/workflows/xlights-wiki-watch.yml`, logic in `.github/wiki-watch/watch.py`) runs every other day. It syncs the xLights source fork, then opens a **wiki-review** issue that lists new changelog entries and effect-option changes, grouped by the wiki page they affect.
- **Reviewing:** work through each wiki-review issue's checklist, update the wiki pages, then close the issue.
- **Page marker:** pages rewritten for the wiki end with a `<!-- maintained-in-wiki: ... -->` line, so the old manual-to-wiki converter never overwrites them.
- **Publishing:** changes are previewed on the [test wiki](https://github.com/derwin12/manual/wiki) first, then pushed to the official wiki.

History: the overview is [#10](https://github.com/derwin12/manual/issues/10), the per-chapter issues are #1-#9, and the screenshot refresh is #19.
