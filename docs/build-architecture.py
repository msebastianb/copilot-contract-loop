#!/usr/bin/env python3
"""Generates docs/architecture.svg for copilot-contract-loop.

The contract-first loop: the phases, the inner loop with its return path, the
escalation route and the exit codes. The layout is a two-row snake so the text
stays readable at GitHub's ~830 px width. Regenerate with:
    python3 docs/build-architecture.py
"""
import pathlib

W, H = 1000, 780
BG, GRID = "#020617", "#1e293b"
INK, MUTED, FAINT, WARN = "#e2e8f0", "#94a3b8", "#64748b", "#fda4af"
MONO = "ui-monospace, SFMono-Regular, 'JetBrains Mono', Menlo, Consolas, monospace"

# kind -> (stroke, fill)
C = {
    "violet":  ("#a78bfa", "rgba(76,29,149,0.42)"),
    "amber":   ("#fbbf24", "rgba(120,53,15,0.32)"),
    "emerald": ("#34d399", "rgba(6,78,59,0.45)"),
    "slate":   ("#94a3b8", "rgba(30,41,59,0.62)"),
    "cyan":    ("#22d3ee", "rgba(8,51,68,0.45)"),
    "pink":    ("#f472b6", "rgba(131,24,67,0.40)"),
    "green":   ("#4ade80", "rgba(6,78,59,0.30)"),
    "rose":    ("#fb7185", "rgba(136,19,55,0.35)"),
    "sky":     ("#38bdf8", "rgba(8,47,73,0.45)"),
}
LINE = {k: v[0] for k, v in C.items()}

out = []
add = out.append


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def box(x, y, w, h, kind, title, subs, dash=None, title_size=16, sub_size=12.5):
    stroke, fill = C[kind]
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#0b1220"/>')
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" '
        f'stroke-width="1.6"{d}/>')
    ty = y + 30 if subs else y + h / 2 + 6
    add(f'<text x="{x + w/2}" y="{ty}" fill="{INK}" font-size="{title_size}" font-weight="600" '
        f'text-anchor="middle" font-family="{MONO}">{esc(title)}</text>')
    for i, sub in enumerate(subs):
        add(f'<text x="{x + w/2}" y="{ty + 20 + i*16.5}" fill="{MUTED}" font-size="{sub_size}" '
            f'text-anchor="middle" font-family="{MONO}">{esc(sub)}</text>')


def marker(kind):
    return (f'<marker id="a-{kind}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{LINE[kind]}"/></marker>')


def arrow(pts, kind="slate", dash=None, label=None, lx=None, ly=None, anchor="middle",
          width=1.6, size: float = 12, color=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    path = "M " + " L ".join(f"{x} {y}" for x, y in pts)
    add(f'<path d="{path}" fill="none" stroke="{LINE[kind]}" stroke-width="{width}"{d} '
        f'marker-end="url(#a-{kind})"/>')
    if label:
        add(f'<text x="{lx}" y="{ly}" fill="{color or MUTED}" font-size="{size}" '
            f'text-anchor="{anchor}" font-family="{MONO}">{esc(label)}</text>')


def text(x, y, s, size: float = 12, color=MUTED, anchor="start", weight=None):
    w = f' font-weight="{weight}"' if weight else ""
    add(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" text-anchor="{anchor}"{w} '
        f'font-family="{MONO}">{esc(s)}</text>')


# ---------- document ----------
add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
    f'aria-label="The Copilot contract loop: the Copilot CLI session writes the contract and the acceptance '
    f'checks, cpl.py drives a Haiku coder through them, a typed judge gates what the checks cannot see, and '
    f'cpl.py close reports a verdict">')
add('<defs>')
add(f'<pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">'
    f'<path d="M 40 0 L 0 0 0 40" fill="none" stroke="{GRID}" stroke-width="0.6"/></pattern>')
for k in LINE:
    add(marker(k))
add('</defs>')
add(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
add(f'<rect width="{W}" height="{H}" fill="url(#grid)"/>')
add(f'<rect x="0" y="0" width="{W}" height="3" fill="#38bdf8" opacity="0.75"/>')

text(48, 44, "contract-first coding loop · GitHub Copilot CLI", 20, INK, weight="600")
text(48, 66, "Copilot writes the contract; a script drives a cheap Haiku coder through it.", 12, FAINT)

# 1 - architect and contract
box(48, 100, 330, 104, "violet", "ARCHITECT: Copilot CLI session", [
    "a strong model, used where it pays",
    "writes the checks and the contract,",
    "settles escalations, gives the verdict",
], title_size=15)
box(438, 100, 330, 104, "amber", "contract.json", [
    "stack decision, with a reason",
    "small tasks · allowed globs each",
    "protected checks · launch command",
], title_size=15)
arrow([(378, 152), (430, 152)], "violet", label="writes", lx=404, ly=142)
arrow([(603, 204), (603, 242)], "amber")
text(620, 222, "init: clean tree, branch cpl/<stamp>", 11, FAINT)
text(620, 238, "scout: brief.md · seal: checks fail now", 11, FAINT)

# 2 - the loop
add('<rect x="48" y="250" width="904" height="336" rx="14" fill="rgba(2,6,23,0.55)" '
    'stroke="#334155" stroke-width="1.4" stroke-dasharray="9,5"/>')
text(68, 276, "THE LOOP: cpl.py run", 13.5, INK, weight="600")

box(72, 316, 250, 104, "emerald", "CODER", [
    "copilot -p, claude-haiku-4.5", "fresh home, no AGENTS.md", "sees only its task spec",
], title_size=15)
box(362, 316, 250, 104, "slate", "WORKING TREE", [
    "revert guard per attempt:", "protected and out-of-scope", "files are thrown away",
], title_size=15)
box(652, 316, 250, 104, "cyan", "CHECKS", [
    "your commands", "the only source of truth", "for “done”",
], title_size=15)
box(652, 452, 250, 96, "pink", "JUDGE", [
    "copilot -p, view only", "scope · risk · screenshot", "doubt goes to you",
], title_size=15)
box(362, 452, 250, 96, "green", "COMMIT cpl(<task>)", [
    "one commit per task", "on branch cpl/<stamp>",
], title_size=14)

arrow([(322, 368), (354, 368)], "emerald", label="edits", lx=338, ly=358, size=11.5)
arrow([(612, 368), (644, 368)], "slate", label="runs", lx=628, ly=358, size=11.5)
arrow([(777, 420), (777, 444)], "cyan", label="pass", lx=789, ly=440, anchor="start", size=11.5)
arrow([(644, 500), (620, 500)], "pink", label="green", lx=632, ly=490, size=11.5)

# return path: next task
arrow([(375, 548), (375, 562), (197, 562), (197, 428)], "emerald")
text(487, 578, "next task: the loop repeats until every task has a commit", 11.5, MUTED, anchor="middle")

# failure path inside the loop
arrow([(777, 316), (777, 292), (197, 292), (197, 308)], "rose", dash="6,5")
text(487, 286, "fail: the same failure twice escalates · hard cap of 3 attempts", 11.5, WARN, anchor="middle")

# 3 - escalation back to the architect
box(48, 634, 320, 96, "rose", "ESCALATION PACKET · exit 3", [
    "spec · last failure · last diff", "you decide: cpl.py resolve <task>", "or cpl.py run --retry <task>",
], dash="6,4", title_size=14)
arrow([(337, 292), (337, 620), (208, 620), (208, 630)], "rose", dash="6,4")
arrow([(28, 682), (28, 152), (40, 152)], "violet", dash="6,5", width=1.4)
text(54, 232, "architect settles it, the loop carries on", 11, MUTED)

# 4 - close and exit codes
box(400, 634, 340, 96, "sky", "cpl.py close", [
    "reruns every check, launches the product",
    "writes close.md: verdict, task table,",
    "only the risky or unjudged diffs",
], title_size=15)
box(760, 634, 192, 96, "slate", "exit codes", [
    "0 done · 2 usage", "3 escalation · 4 failed", "no launch, no close",
], title_size=14, sub_size=11.5)
arrow([(900, 586), (900, 612), (570, 612), (570, 630)], "sky", dash="6,4")
text(735, 606, "every task done", 11.5, MUTED, anchor="middle")

add('</svg>')

path = pathlib.Path(__file__).with_name("architecture.svg")
path.write_text("\n".join(out) + "\n")
print("wrote", path, path.stat().st_size, "bytes")
