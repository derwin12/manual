"""Turn new xLights commits into a wiki review checklist.

Compares two commits of the xLights repo and opens one GitHub issue listing,
grouped by wiki page:

* new ``-enh`` / ``-change`` entries in README.txt (the changelog)
* option changes in resources/effectmetadata/*.json (added / removed /
  relabelled options, new choices) -- the Effect-* wiki pages must match these

Used by .github/workflows/xlights-wiki-watch.yml; also runs locally:

    python .github/wiki-watch/watch.py --local-repo H:/XlightsSourceDir/xLights \
        --old 2026.01-commit --new HEAD --wiki-dir H:/XlightsSourceDir/xLights.wiki --dry-run

Standard library only.  GITHUB_TOKEN is used for API calls when set.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

API = "https://api.github.com"
WIKI_URL = "https://github.com/{repo}/wiki/"
ISSUE_LIMIT = 60000  # GitHub caps issue bodies at 65536 chars
CHANGELOG = "README.txt"
METADATA_DIR = "resources/effectmetadata/"

# --------------------------------------------------------------------------
# Changelog entry -> wiki page rules.  First column is a regex (case-insensitive)
# tried against the entry text; an entry can land on up to MAX_PAGES pages.
# Effect and model pages are matched separately from the wiki's page list.
# --------------------------------------------------------------------------
MAX_PAGES = 3
KEYWORD_RULES = [
    (r"\bFPP Connect\b", "FPP-Connect"),
    (r"\bFile\s*>", "Menus-File"),
    (r"\bEdit\s*>", "Menus-Edit"),
    (r"\bTools\s*>", "Menus-Tools"),
    (r"\bView\s*>", "Menus-View"),
    (r"\bAudio\s*>", "Menus-Audio"),
    (r"\bImport\s*>|\bImport Effects\b|\bSuperStar\b|\bLOR S[56]\b|\bVixen\b|\bimport(ing)? sequences?\b", "Menus-Import"),
    (r"\bHelp\s*>", "Menus-Help"),
    (r"\bPreferences?\b", "File-Preferences"),
    (r"\bSequence Settings\b", "Sequence-Settings"),
    (r"\bBatch Render\b|\bPackage Sequence\b|\bpackag(e|ing) a sequence\b", "Menus-Tools"),
    (r"\b(base )?show (folder|directory)\b", "Show-Directory"),
    (r"\bvisuali[sz]er?\b", "Controller-Visualizer"),
    (r"\bcontrollers?\b|\bcontroller connection\b|\bFPP (string )?(capes?|hats?)\b|\b(Falcon|HinksPix|PixLite|ESPixelStick|Genius|Experience|SanDevices|AlphaPix|ILT)\b|\bE1\.31\b|\bArt-?Net\b|\bDDP\b|\bserial (ports?|outputs?)\b", "Controllers-Settings"),
    (r"\bmodel groups?\b", "Model-Groups"),
    (r"\bsub ?models?\b", "Layout-Tab-SubModels"),
    (r"\b(model )?states?\b(?! effect)|\bnode select\b|\bfaces? (definition|tab)\b", "Model-Settings"),
    (r"\bLayout( tab)?\b|\bterrain\b|\b3D (objects?|view|mode|models?)\b", "Layout-Tab-Layout"),
    (r"\bCheck Sequence\b", "Menus-Tools"),
    (r"\bkey ?bindings?\b", "Keyboard-Shortcuts"),
    (r"\bsequencer grid\b|\bSelect Effects panel\b|\beffects? grid\b", "Sequencer-Tab-Sequencer"),
    (r"\bstem separation\b|\bstems?\b|\bwaveform\b", "Menus-Audio"),
    (r"\bcrash reports?\b", "Menus-Help"),
    (r"^macOS\b|\bmacOS:", "Installation-MacOS"),
    (r"^Linux\b|\bLinux:", "Installation-Linux"),
    (r"^Windows\b|\bWindows:", "Installation-Windows"),
    (r"\bvalue curves?\b", "Value-Curves"),
    (r"\btiming (tracks?|marks?)\b|\bmetronome\b", "Timing-Tracks"),
    (r"\bsong structure\b", "Song-Structure-Regions"),
    (r"\bcommand palette\b", "Command-Palette"),
    (r"\bpresets?\b", "Effect-Presets"),
    (r"\bpalette\b|\bcolou?r (picker|buttons?)\b", "Changing-Color-Settings"),
    (r"\blayer blend|\bchroma key\b|\blayers?\b", "Layer-Blending"),
    (r"\blip.?sync\b|\bphonemes?\b|\bsinging faces\b", "Singing-Faces"),
    (r"\bdisplay elements\b|\bmaster view\b", "Sequencer-Tab-Views"),
    (r"\bperspectives?\b", "View-Perspectives"),
    (r"\bbackups?\b", "Backup-and-Recovery"),
    (r"\bLua\b|\bscripts?\b", "Lua-Scripting"),
    (r"\bAI\b|\bGemini\b|\bChatGPT\b|\bOllama\b|\bClaude\b", "Preferences-Services"),
    (r"\bkeyboard shortcuts?\b|\bhot ?keys?\b", "Keyboard-Shortcuts"),
    (r"\brender(s|ing)?\b", "Sequencer-Tab-Rendering"),
]
# Effect names that are also ordinary words: only match "<Name> effect" or a
# leading "<Name>:".  Every other effect name matches anywhere as a word.
COMMON_WORD_EFFECTS = {"On", "Off", "Fill", "Text", "Music", "Video", "State", "Tree", "Shape",
                       "Lines", "Wave", "Warp", "Fan", "Life", "Piano", "Adjust", "Duplicate",
                       "Bars", "Faces", "Pictures", "Fire", "DMX", "Moving Head", "Circles"}
# resources/effectmetadata/shared/*.json describe sequencer panels, not effects
SHARED_PANEL_PAGES = {"Buffer": "Layer-Settings", "Blending": "Layer-Blending", "Color": "Changing-Color-Settings"}
EFFECT_ALIASES = {"Effect-Snowstorm": ["Snow Storm"], "Effect-SingleStrand": ["Single Strand FX"],
                  "Effect-Tendril": ["Tendrils"], "Effect-Pictures": ["Picture"]}
MODEL_ALIASES = {"PolyLine-Model": ["Poly ?Line"], "Icicles-Model": ["Icicles?"], "Arches-Model": ["Arch(es)?"],
                 "Candy-Cane-Model": ["Candy ?Canes?"], "Window-Frame-Model": ["Window Frame"],
                 "Channel-Block-Model": ["Channel Block"], "Spinner-Model": ["Spinners?"],
                 "Wreath-Model": ["Wreaths?"], "Sphere-Model": ["Spheres?"], "Cube-Model": ["Cubes?"],
                 "Star-Model": ["Stars? model"], "Tree-Model": ["Tree model"], "Matrix-Model": ["Matrix model"],
                 "Custom-Model": ["Custom models?"], "Image-Model": ["Image models?"],
                 "Circle-Model": ["Circle models?"], "Label-Model": ["Label models?"],
                 "Single-Line-Model": ["Single Line"], "DMX-Model": ["DMX models?", "moving heads?\\b(?! effect)"]}


# --------------------------------------------------------------------------
# Fetching file contents at a commit: local clone or GitHub API
# --------------------------------------------------------------------------
class Source:
    def __init__(self, repo: str, local: str | None, token: str | None):
        self.repo, self.local, self.token = repo, local, token

    def _api(self, path: str, data: dict | None = None, method: str | None = None):
        req = urllib.request.Request(API + path, method=method or ("POST" if data else "GET"),
                                     data=json.dumps(data).encode() if data else None)
        req.add_header("Accept", "application/vnd.github+json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    def head(self, branch: str) -> str:
        if self.local:
            return self._git("rev-parse", branch).strip()
        return self._api(f"/repos/{self.repo}/commits/{branch}")["sha"]

    def _git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", self.local, *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=True, stdin=subprocess.DEVNULL).stdout

    def resolve(self, ref: str) -> str:
        return self._git("rev-parse", ref).strip() if self.local else ref

    def changed_files(self, old: str, new: str) -> list[str]:
        if self.local:
            return self._git("diff", "--name-only", old, new).split()
        files, page = [], 1
        while True:
            r = self._api(f"/repos/{self.repo}/compare/{old}...{new}?per_page=100&page={page}")
            batch = [f["filename"] for f in r.get("files", [])]
            files += batch
            if len(batch) < 100:
                return files
            page += 1

    def read(self, path: str, sha: str) -> str | None:
        if self.local:
            r = subprocess.run(["git", "-C", self.local, "show", f"{sha}:{path}"], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
            return r.stdout if r.returncode == 0 else None
        url = f"https://raw.githubusercontent.com/{self.repo}/{sha}/{path}"
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise


# --------------------------------------------------------------------------
# Changelog parsing
# --------------------------------------------------------------------------
ENTRY = re.compile(r"^\s*-\s*(enh|bug|change|fix)\s*(?:\(([^)]*)\))?\s*(.*)$", re.I)
VERSION = re.compile(r"^\s*(20\d\d\.\d+(?:\.\d+)?)\s+\S")


def parse_changelog(text: str) -> list[dict]:
    entries, version, cur = [], "", None
    for line in text.splitlines():
        v = VERSION.match(line)
        if v and not line.startswith(" " * 8):
            version, cur = v.group(1), None
            continue
        m = ENTRY.match(line)
        if m:
            cur = {"version": version, "kind": m.group(1).lower(), "author": (m.group(2) or "").strip(),
                   "text": m.group(3).strip()}
            entries.append(cur)
        elif cur and line.strip():
            if not line.startswith((" ", "\t")):  # left-aligned prose ends the entry
                cur = None
                continue
            sub = line.strip()
            cur["text"] += ("\n  " + sub) if sub.startswith("- ") else (" " + sub)
        elif not line.strip():
            pass
    return entries


def entry_key(e: dict) -> tuple:
    return e["kind"], e["author"].lower(), " ".join(e["text"].split()).lower()


def new_entries(old_text: str | None, new_text: str) -> list[dict]:
    seen = {entry_key(e) for e in parse_changelog(old_text or "")}
    return [e for e in parse_changelog(new_text)
            if e["kind"] in ("enh", "change") and entry_key(e) not in seen]


# --------------------------------------------------------------------------
# Effect metadata diff
# --------------------------------------------------------------------------
def metadata_changes(old: str | None, new: str | None) -> tuple[str, list[str]]:
    o = json.loads(old) if old else {"properties": []}
    n = json.loads(new) if new else {"properties": []}
    name = n.get("effectName") or o.get("effectName") or "?"
    if not new:
        return name, ["effect metadata file removed"]
    op = {p["id"]: p for p in o.get("properties", []) if "id" in p}
    np_ = {p["id"]: p for p in n.get("properties", []) if "id" in p}
    if not old:
        return name, [f"metadata file added ({len(np_)} options): check the page's options table against it"]
    out = []
    for pid in np_.keys() - op.keys():
        p = np_[pid]
        out.append(f"new option **{p.get('label', pid)}** (`{pid}`, {p.get('controlType', p.get('type', ''))})")
    for pid in op.keys() - np_.keys():
        out.append(f"option removed: **{op[pid].get('label', pid)}** (`{pid}`)")
    for pid in op.keys() & np_.keys():
        a, b = op[pid], np_[pid]
        if a.get("label") != b.get("label"):
            out.append(f"option renamed: **{a.get('label')}** -> **{b.get('label')}** (`{pid}`)")
        ao, bo = a.get("options") or [], b.get("options") or []
        added = [x for x in bo if x not in ao]
        gone = [x for x in ao if x not in bo]
        if added:
            out.append(f"**{b.get('label', pid)}**: new choice{'s' * (len(added) > 1)} " + ", ".join(f"`{x}`" for x in added))
        if gone:
            out.append(f"**{b.get('label', pid)}**: choice{'s' * (len(gone) > 1)} removed " + ", ".join(f"`{x}`" for x in gone))
        for k in ("default", "min", "max"):
            if k in a and k in b and a[k] != b[k]:
                out.append(f"**{b.get('label', pid)}**: {k} {a[k]} -> {b[k]}")
    return name, out


# --------------------------------------------------------------------------
# Page matching
# --------------------------------------------------------------------------
def split_camel(s: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)


class Matcher:
    def __init__(self, pages: set[str]):
        self.pages = pages
        self.effect_res = []
        for p in sorted(x for x in pages if x.startswith("Effect-")):
            name = split_camel(p[len("Effect-"):])
            names = [name] + EFFECT_ALIASES.get(p, [])
            if name in COMMON_WORD_EFFECTS:
                pat = "|".join(rf"^{re.escape(n)}\s*(effect)?\s*[:\-]|\b{re.escape(n)} effects?\b" for n in names)
            else:
                pat = "|".join(rf"\b{re.escape(n)}\b" for n in names)
            self.effect_res.append((re.compile(pat, re.I), p))
        self.model_res = [(re.compile("|".join(rf"\b{a}\b" for a in aliases), re.I), p)
                          for p, aliases in MODEL_ALIASES.items() if p in pages]
        self.keyword_res = [(re.compile(rx, re.I), p) for rx, p in KEYWORD_RULES if p in pages]

    def effect_page(self, effect_name: str) -> str | None:
        key = re.sub(r"[^a-z0-9]", "", effect_name.lower())
        for p in self.pages:
            if p.startswith("Effect-") and re.sub(r"[^a-z0-9]", "", p[7:].lower()) in (key, key.rstrip("s")):
                return p
        return None

    def match(self, text: str) -> list[str]:
        hits: list[str] = []
        for rx, page in self.effect_res + self.model_res + self.keyword_res:
            if page not in hits and rx.search(text):
                hits.append(page)
            if len(hits) >= MAX_PAGES:
                break
        return hits


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def build_report(entries, meta, matcher: Matcher, wiki_repo: str, header: str) -> list[str]:
    by_page: dict[str, list[str]] = defaultdict(list)
    for name, changes in meta:
        page = (SHARED_PANEL_PAGES.get(name) or matcher.effect_page(name)
                or f"Effect-{name.replace(' ', '')}")
        for c in changes:
            by_page[page].append(f"- [ ] metadata: {c}")
    unsorted = []
    for e in entries:
        who = f" ({e['author']})" if e["author"] else ""
        line = f"- [ ] **{e['version']}**{who} {e['text']}" if e["version"] else f"- [ ] {e['text']}"
        pages = matcher.match(e["text"])
        if not pages:
            unsorted.append(line)
        for p in pages:
            by_page[p].append(line)

    base = WIKI_URL.format(repo=wiki_repo)
    sections = []
    for page in sorted(by_page):
        exists = page in matcher.pages
        title = f"### [{page}]({base}{page})" if exists else f"### {page} (no wiki page yet)"
        sections.append("\n".join([title, *by_page[page]]))
    if unsorted:
        sections.append("\n".join(["### Unsorted: pick a page or tick if not doc-relevant", *unsorted]))

    footer = ("\n---\nTick an item once the wiki covers it (or it needs no doc change). "
              "Entries can appear under more than one page; tick each where it applies.")
    bodies, cur = [], header
    for s in sections:
        if len(cur) + len(s) + len(footer) > ISSUE_LIMIT:
            bodies.append(cur + footer)
            cur = header + "\n*(continued)*\n"
        cur += "\n\n" + s
    bodies.append(cur + footer)
    return bodies


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="derwin12/xLights")
    ap.add_argument("--branch", default="master")
    ap.add_argument("--local-repo", help="read commits from a local clone instead of the API")
    ap.add_argument("--state", default=".github/wiki-watch/last-sha", help="file holding the last processed commit")
    ap.add_argument("--old", help="override the starting commit (default: --state file)")
    ap.add_argument("--new", help="override the end commit (default: head of --branch)")
    ap.add_argument("--wiki-dir", required=True, help="checkout of the wiki (for the page list)")
    ap.add_argument("--wiki-repo", default="derwin12/manual", help="repo whose wiki the links point at")
    ap.add_argument("--issue-repo", default="derwin12/manual")
    ap.add_argument("--labels", default="wiki-review,wiki-migration")
    ap.add_argument("--dry-run", action="store_true", help="print the issue instead of opening it")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    src = Source(args.repo, args.local_repo, os.environ.get("GITHUB_TOKEN"))
    state = Path(args.state)
    new = src.resolve(args.new) if args.new else src.head(args.branch)
    old = src.resolve(args.old) if args.old else (state.read_text().strip() if state.exists() else "")
    if not old:
        print(f"No previous commit recorded; starting from {new[:9]}. Next run reports changes after it.")
        if not args.dry_run:
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(new + "\n")
        return 0
    if old == new:
        print(f"No new commits since {old[:9]}.")
        return 0

    files = src.changed_files(old, new)
    entries = new_entries(src.read(CHANGELOG, old), src.read(CHANGELOG, new) or "") if CHANGELOG in files else []
    meta = []
    for f in files:
        if f.startswith(METADATA_DIR) and f.endswith(".json"):
            name, changes = metadata_changes(src.read(f, old), src.read(f, new))
            if changes:
                meta.append((name, changes))

    pages = {p.stem for p in Path(args.wiki_dir).glob("*.md")}
    matcher = Matcher(pages)
    versions = sorted({e["version"] for e in entries if e["version"]})
    span = f"{versions[0]}–{versions[-1]}" if len(versions) > 1 else (versions[0] if versions else "")
    title = f"Wiki review: xLights {span}".strip() + f" ({old[:7]}..{new[:7]})"
    header = "\n".join([
        f"New xLights changes that may need wiki updates: "
        f"[{old[:7]}...{new[:7]}](https://github.com/{args.repo}/compare/{old}...{new}) "
        f"({len(entries)} changelog entries, {sum(len(c) for _, c in meta)} effect-option changes).",
    ])

    if not entries and not meta:
        print(f"{len(files)} files changed, nothing doc-relevant.")
    else:
        bodies = build_report(entries, meta, matcher, args.wiki_repo, header)
        print(f"{len(entries)} entries, {len(meta)} effects with option changes, {len(bodies)} issue(s)")
        for i, body in enumerate(bodies, 1):
            t = title + (f" [{i}/{len(bodies)}]" if len(bodies) > 1 else "")
            if args.dry_run:
                print(f"\n===== {t}\n{body}")
            else:
                issue = src._api(f"/repos/{args.issue_repo}/issues",
                                 {"title": t, "body": body, "labels": [l for l in args.labels.split(",") if l]})
                print(f"opened {issue['html_url']}")

    if not args.dry_run:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(new + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
