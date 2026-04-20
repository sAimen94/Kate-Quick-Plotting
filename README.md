# Kate Quick-Plot

Select two (or more) columns of numbers in Kate, hit a shortcut, get an instant Y-vs-X plot.
Built for visually inspecting convergence / residual output files.

## 1. Install Kate

```bash
# Debian/Ubuntu
sudo apt install kate python3-matplotlib python3-numpy
# Arch
sudo pacman -S kate python-matplotlib python-numpy
# Fedora
sudo dnf install kate python3-matplotlib python3-numpy
```

## 2. Install the plot script

```bash
mkdir -p ~/.local/bin
cp kate_quickplot.py ~/.local/bin/
chmod +x ~/.local/bin/kate_quickplot.py
```

## 3. Register the External Tool in Kate

Kate → **Settings → Configure Kate → External Tools → New…**

Fill in exactly:

| Field         | Value                                  |
| ------------- | -------------------------------------- |
| Name          | `Quick-Plot Selection`                 |
| Icon          | `office-chart-line` (any icon is fine) |
| Executable    | `python3`                              |
| Arguments     | `%{ENV:HOME}/.local/bin/kate_quickplot.py` |
| Input         | `%{Document:Selection:Text}`           |
| Output        | Ignore                                 |
| Working Dir   | `%{Document:Path}`                     |
| Command       | `quickplot`                            |

Kate expands `%{Document:Selection:Text}` in the **Input** field and pipes that
text into the script's stdin — exactly what `kate_quickplot.py` expects.

### Assign the keyboard shortcut

Settings → Configure Shortcuts  → Quick-Plot Selection →
use e.g. `Ctrl+Alt+P` → Apply.

## 4. Use it

1. Open a file containing two-column numeric data (OpenFOAM log residuals, preCICE
   iteration counters, anything).
2. Select the rows you want to plot (comment lines starting with `#`, `//`, `%`
   are skipped automatically).
3. Press `Ctrl+Alt+P`. A matplotlib window pops up with Y vs X.

Supported separators (auto-detected): spaces, tabs, commas, semicolons.

## Troubleshooting

- **Nothing happens** → open Kate from a terminal; stderr from the script prints there.
- **No plot window on a remote/Wayland session** → ensure `$DISPLAY` (X11) or
  `$WAYLAND_DISPLAY` is set for Kate; matplotlib's Qt/Tk backends need it.
