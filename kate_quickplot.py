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

Interactive controls (in the plot window):
    Left-click a legend entry   : show/hide that curve
    Right-click a legend entry  : mark it as a "relative error" source
                                   (fraction, e.g. 0.05 = 5%, not absolute
                                   sd/std). Then left-click a different
                                   legend entry to attach that relative
                                   error to it -> the target curve is
                                   redrawn as an errorbar plot with
                                   yerr = y * relative_error, and both
                                   original curves are hidden.
    'a'                          : show all curves (does not undo pairings)
    'u'                          : undo the most recent error-bar pairing
    'r'                          : full reset (undo all pairings, show all)
    't'                          : arm/disarm threshold-line placement mode;
                                   while armed, left-click anywhere on the
                                   axes (not on a legend entry) to draw a
                                   dashed horizontal line at that y-value.
                                   Pressing 't' again while a line exists
                                   removes it instead of re-arming.
    'm'                          : toggle a moving-average overlay (dashed,
                                   same color, thinner) on all currently
                                   visible curves. Window size is auto-set
                                   to max(3, npoints // 20).
    Plot axes autoscale to only the currently visible curves after every
    toggle or pairing/undo/reset action.
"""
import sys
import re
import argparse
import os
import math


SPLITTER = re.compile(r"[,\s;]+")


def _normalize_number_text(s):
    return (
        s.replace("−", "-")
         .replace("–", "-")
         .replace("—", "-")
    )


def _tokens(s):
    s = _normalize_number_text(s)
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
        line = _normalize_number_text(raw.strip())
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
            vals = [float(p) for p in _tokens(stripped)]
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


def _is_visible(artist):
    """Works for both Line2D and ErrorbarContainer."""
    if hasattr(artist, "get_visible"):
        return artist.get_visible()
    return artist.get_children()[0].get_visible()


def _set_artist_visible(artist, visible):
    """Works for both Line2D and ErrorbarContainer."""
    if hasattr(artist, "set_visible"):
        artist.set_visible(visible)
    else:
        for part in artist.get_children():
            part.set_visible(visible)


def _enable_legend_toggle(fig, ax):
    """
    Wire up interactive legend controls on `ax`. See module docstring for
    the full control list. State (pairings, pending selection, legend
    object) is kept in a closure dict `state` so the legend can be rebuilt
    freely after every structural change (hide/show, add/remove errorbar)
    without losing track of which text/handle belongs to which curve.
    """
    state = {
        "pending_err": None,   # line marked via right-click, awaiting target
        "history": [],         # stack of (target_line, err_line, errbar_container)
        "errorbar_containers": [],
        "legend": None,
        "text_to_artist": {},
        "handle_to_artist": {},
        "artist_to_text": {},
        "threshold_armed": False,
        "threshold_line": None,
        "ma_active": False,
        "ma_lines": [],        # overlay Line2D objects created for moving avg
    }

    def _rebuild_registry():
        leg = ax.legend(loc="best", fontsize=9)
        state["legend"] = leg

        try:
            handles = leg.legend_handles
        except AttributeError:
            handles = leg.legendHandles
        texts = leg.get_texts()

        label_to_artist = {}
        for ln in ax.get_lines():
            label_to_artist[ln.get_label()] = ln
        for cont in state["errorbar_containers"]:
            label_to_artist[cont.get_label()] = cont

        text_to_artist = {}
        for text, handle in zip(texts, handles):
            artist = label_to_artist.get(text.get_text())
            if artist is not None:
                text_to_artist[text] = artist
        handle_to_artist = {
            h: text_to_artist[t] for t, h in zip(texts, handles) if t in text_to_artist
        }
        artist_to_text = {v: k for k, v in text_to_artist.items()}

        for text in texts:
            text.set_picker(True)
        for handle in handles:
            handle.set_picker(True)

        state["text_to_artist"] = text_to_artist
        state["handle_to_artist"] = handle_to_artist
        state["artist_to_text"] = artist_to_text

    def _rescale():
        ax.relim(visible_only=True)
        ax.autoscale_view()

    def _refresh(rescale=True):
        _rebuild_registry()
        if rescale:
            _rescale()
        fig.canvas.draw_idle()

    def _artist_from_pick(artist):
        return state["text_to_artist"].get(artist) or state["handle_to_artist"].get(artist)

    def _set_visibility(artist, visible):
        _set_artist_visible(artist, visible)
        text = state["artist_to_text"].get(artist)
        if text is not None:
            text.set_alpha(1.0 if visible else 0.3)

    def _apply_relative_error(target_line, err_line):
        x = target_line.get_xdata()
        y = target_line.get_ydata()
        rel = err_line.get_ydata()
        yerr = [yi * ri for yi, ri in zip(y, rel)]
        color = target_line.get_color()
        label = target_line.get_label()

        target_line.set_visible(False)
        err_line.set_visible(False)

        errbar = ax.errorbar(
            x, y, yerr=yerr, fmt="o-", color=color, linewidth=1.2,
            markersize=3.5, capsize=3, label=f"{label} (\u00b1rel.err)"
        )
        state["errorbar_containers"].append(errbar)
        state["history"].append((target_line, err_line, errbar))
        _refresh()

    def _undo_last():
        if not state["history"]:
            return
        target_line, err_line, errbar = state["history"].pop()
        errbar.remove()
        state["errorbar_containers"].remove(errbar)
        target_line.set_visible(True)
        err_line.set_visible(True)
        _refresh()

    def _reset_all():
        while state["history"]:
            target_line, err_line, errbar = state["history"].pop()
            errbar.remove()
            state["errorbar_containers"].remove(errbar)
            target_line.set_visible(True)
            err_line.set_visible(True)

        if state["threshold_line"] is not None:
            state["threshold_line"].remove()
            state["threshold_line"] = None
        state["threshold_armed"] = False

        _clear_moving_average()
        state["ma_active"] = False

        state["pending_err"] = None

        for line in ax.get_lines():
            line.set_visible(True)

        _refresh()

    def _toggle_threshold():
        if state["threshold_line"] is not None:
            state["threshold_line"].remove()
            state["threshold_line"] = None
            state["threshold_armed"] = False
            fig.canvas.draw_idle()
        else:
            state["threshold_armed"] = not state["threshold_armed"]

    def _place_threshold(y_value):
        if state["threshold_line"] is not None:
            state["threshold_line"].remove()
        state["threshold_line"] = ax.axhline(
            y_value, color="black", linestyle="--", linewidth=1.2, alpha=0.8,
            label=f"threshold={y_value:.4g}"
        )
        state["threshold_armed"] = False
        fig.canvas.draw_idle()

    def _moving_average(y, window):
        n = len(y)
        if n == 0:
            return y
        half = window // 2
        out = []
        for i in range(n):
            lo = max(0, i - half)
            hi = min(n, i + half + 1)
            out.append(sum(y[lo:hi]) / (hi - lo))
        return out

    def _clear_moving_average():
        for ma_line in state["ma_lines"]:
            ma_line.remove()
        state["ma_lines"] = []

    def _toggle_moving_average():
        if state["ma_active"]:
            _clear_moving_average()
            state["ma_active"] = False
            fig.canvas.draw_idle()
            return

        cap_lines = set()
        for cont in state["errorbar_containers"]:
            cap_lines.update(cont[1])  # cap-marker Line2D artists, exclude

        skip = cap_lines | set(state["ma_lines"])
        if state["threshold_line"] is not None:
            skip.add(state["threshold_line"])

        for line in ax.get_lines():
            if line in skip or not _is_visible(line):
                continue
            y = line.get_ydata()
            x = line.get_xdata()
            window = max(3, len(y) // 20)
            ma_y = _moving_average(list(y), window)
            ma_line, = ax.plot(
                x, ma_y, linestyle="--", linewidth=1.5,
                color=line.get_color(), alpha=0.9,
                label=f"{line.get_label()} (MA{window})"
            )
            state["ma_lines"].append(ma_line)
        state["ma_active"] = True
        _refresh()

    def on_pick(event):
        artist = _artist_from_pick(event.artist)
        if artist is None:
            return

        if event.mouseevent.button == 3:
            state["pending_err"] = artist
            fig.canvas.draw_idle()
            return

        pending = state["pending_err"]
        if pending is not None and pending is not artist:
            state["pending_err"] = None
            _apply_relative_error(artist, pending)
            return

        _set_visibility(artist, not _is_visible(artist))
        _rescale()
        fig.canvas.draw_idle()

    def on_click(event):
        # Only handle plain axes clicks for threshold placement; legend
        # picks are handled by on_pick and arrive as separate events.
        if not state["threshold_armed"]:
            return
        if event.inaxes is not ax or event.ydata is None:
            return
        _place_threshold(event.ydata)

    def on_key(event):
        if event.key == "a":
            for artist in state["text_to_artist"].values():
                _set_visibility(artist, True)
            _rescale()
            fig.canvas.draw_idle()
        elif event.key == "u":
            _undo_last()
        elif event.key == "r":
            _reset_all()
        elif event.key == "t":
            _toggle_threshold()
        elif event.key == "m":
            _toggle_moving_average()

    _refresh(rescale=False)
    fig.canvas.mpl_connect("pick_event", on_pick)
    fig.canvas.mpl_connect("button_press_event", on_click)
    fig.canvas.mpl_connect("key_press_event", on_key)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logy", action="store_true")
    ap.add_argument("--logx", action="store_true")
    ap.add_argument(
        "--auto-log-decades",
        type=float,
        default=4.0,
        help="auto-enable log Y if positive data spans >= N decades "
             "(default 4; set to 0 to disable)"
    )
    ap.add_argument(
        "--title",
        default="Kate Quick-Plot",
        help="plot title; pass %%{Document:FileName} from Kate"
    )
    args = ap.parse_args()

    if not args.title:
        args.title = "Kate Quick-Plot"

    text = sys.stdin.read()
    if not text.strip():
        sys.stderr.write("kate_quickplot: empty selection on stdin\n")
        sys.exit(2)

    rows, skipped, ncols, headers = parse_selection(text)
    if len(rows) < 2:
        sys.stderr.write(
            f"kate_quickplot: need ≥2 numeric rows, got {len(rows)} "
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
        f"{args.title}  —  {len(rows)} pts × {len(ys)} series{scale_tag}"
    )
    fig.canvas.manager.set_window_title(args.title)

    has_legend = len(ys) > 1 or bool(headers)

    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()

    out = os.environ.get("KATE_QUICKPLOT_OUT")
    if out:
        if has_legend:
            ax.legend(loc="best", fontsize=9)
        fig.savefig(out, dpi=130)
        print(f"Saved plot to {out}")
    else:
        if has_legend:
            _enable_legend_toggle(fig, ax)
        plt.show()


if __name__ == "__main__":
    main()
