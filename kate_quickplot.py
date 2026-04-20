#!/usr/bin/env python3
"""
kate_quickplot.py
Reads selected text from stdin and opens a matplotlib window.

Supported column layouts (auto-detected):
    1 column : Y              -> plotted vs. row index (0..N-1)
    2 columns: X, Y           -> Y vs. X
    N columns: X, Y1, Y2, ... -> each Y_i vs. X on the same axes

An optional header line (last non-numeric line immediately above the first
numeric row) is used for axis/legend labels. Duplicate header names are
disambiguated as name, name_2, name_3, ...

Separators auto-detected: whitespace, tab, comma, semicolon.
Comment lines starting with '#', '//', '%' are skipped (but a '#'-prefixed
header line is still accepted as header).

Flags:
    --logy / --logx        : force log axes
    --auto-log-decades N   : auto-enable log Y if positive data spans >= N
                             decades (default 4; set to 0 to disable)
    --title TEXT           : plot title
"""
import sys
import re
import argparse
import os
import math


SPLITTER = re.compile(r"[,\s;]+")


def _tokens(s):
    return [p for p in SPLITTER.split(s.strip()) if p]


def _all_numeric(tokens):
    if not tokens:
        return False
    try:
        [float(p) for p in tokens]
    except ValueError:
        return False
    return True


def _dedup(names):
    seen = {}
    out = []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}_{seen[n]}")
        else:
            seen[n] = 1
            out.append(n)
    return out


def parse_selection(text):
    """Return (rows, skipped, ncols, headers).

    'headers' is None if no header was detected, else a list of length ncols.
    """
    headers = None
    header_candidate = None
    started = False
    rows = []
    skipped = 0
    ncols = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        stripped = line
        for prefix in ("#", "//", "%"):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):].strip()
                break
        tokens = _tokens(stripped)
        if not tokens:
            continue
        if not started:
            if _all_numeric(tokens):
                started = True
                headers = header_candidate
            else:
                header_candidate = tokens
                continue
        try:
            vals = [float(p) for p in _tokens(line)]
        except ValueError:
            skipped += 1
            continue
        if ncols is None:
            ncols = len(vals)
        if len(vals) != ncols:
            skipped += 1
            continue
        rows.append(vals)

    if headers is not None and ncols:
        if len(headers) == ncols:
            headers = _dedup(headers)
        elif len(headers) == ncols - 1 and ncols >= 2:
            headers = _dedup(["X"] + list(headers))
        else:
            headers = None
    return rows, skipped, ncols or 0, headers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logy", action="store_true")
    ap.add_argument("--logx", action="store_true")
    ap.add_argument("--auto-log-decades", type=float, default=4.0,
                    help="auto-enable log Y if positive data spans >= N decades "
                         "(default 4; set to 0 to disable)")
    ap.add_argument("--title", default="Kate Quick-Plot",
                    help="plot title; pass %%{Document:FileName} from Kate")
    args = ap.parse_args()

    text = sys.stdin.read()
    if not text.strip():
        sys.stderr.write("kate_quickplot: empty selection on stdin\n")
        sys.exit(2)

    rows, skipped, ncols, headers = parse_selection(text)
    if len(rows) < 2:
        sys.stderr.write(
            f"kate_quickplot: need \u22652 numeric rows, got {len(rows)} "
            f"(skipped {skipped} lines)\n"
        )
        sys.exit(3)

    cols = list(zip(*rows))

    if ncols == 1:
        x = list(range(len(rows)))
        ys = [cols[0]]
        ylabels = [headers[0]] if headers else ["Y"]
        xlabel = "row index"
    else:
        x = cols[0]
        ys = cols[1:]
        if headers:
            xlabel = headers[0]
            ylabels = list(headers[1:])
        else:
            xlabel = "X (col 1)"
            ylabels = [f"Y{i}" for i in range(1, ncols)]

    import matplotlib
    if os.environ.get("KATE_QUICKPLOT_HEADLESS"):
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    for y, lbl in zip(ys, ylabels):
        ax.plot(x, y, marker="o", linewidth=1.2, markersize=3.5, label=lbl)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("" if headers and ncols > 2 else "Y")

    auto_logy = False
    if not args.logy and args.auto_log_decades > 0:
        pos = [v for s in ys for v in s if v > 0]
        if len(pos) >= 2:
            span = math.log10(max(pos)) - math.log10(min(pos))
            if span >= args.auto_log_decades:
                auto_logy = True

    scale_tag = ""
    if args.logy or auto_logy:
        ax.set_yscale("log")
        scale_tag = "  [log Y auto]" if auto_logy and not args.logy else "  [log Y]"
    if args.logx and ncols > 1:
        ax.set_xscale("log")

    ax.set_title(
        f"{args.title}  \u2014  {len(rows)} pts \u00d7 {len(ys)} series{scale_tag}"
    )
    fig.canvas.manager.set_window_title(args.title)

    if len(ys) > 1 or headers:
        ax.legend(loc="best", fontsize=9)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()

    out = os.environ.get("KATE_QUICKPLOT_OUT")
    if out:
        fig.savefig(out, dpi=130)
        print(f"Saved plot to {out}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
