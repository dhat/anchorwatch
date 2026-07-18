"""ASCII visualization of recent boat positions relative to the anchor center.

A genuine anchor drag tends to show up as a spatial pattern before the
alarm radius is even crossed: positions normally cluster in an arc
downwind of center rather than swinging evenly all the way around a
circle, and a real drag walks steadily outward instead of staying
contained. This renders a small terminal-friendly density plot of recent
(east, north) offsets from center, in feet, so that pattern is visible at
a glance without needing a GUI -- keeping with the rest of this program's
plain-terminal design.
"""
import math

WIDTH = 41
HEIGHT = 21

# Density shading for how many recent points landed in the same cell --
# index 0 is reserved for "no points here".
DENSITY_CHARS = " .:-=+*#%@"

CENTER_CHAR = '+'
RADIUS_CHAR = 'o'
CURRENT_CHAR = 'B'  # current boat position -- always drawn on top of everything else


def render(points, radius_feet, width=WIDTH, height=HEIGHT, current=None):
    """points: iterable of (east_feet, north_feet) offsets from center.

    current: the boat's current position, as an (east_feet, north_feet)
    tuple, marked distinctly (CURRENT_CHAR) on top of the history/center/
    radius markers -- otherwise the most recent position looks like just
    another history point. If given, it should normally already be one of
    the entries in points (e.g. the last one), so the auto-scaling below
    accounts for it; passing a point outside the range of points may place
    it off the edge of the visible plot.

    Returns a multi-line string: a width x height character grid with the
    center marked, the current alarm radius circle overlaid, recent points
    density-shaded by how often each cell was visited, and the current
    position marked distinctly, followed by a one-line caption.
    """
    points = list(points)
    half_extent = _half_extent(points, radius_feet)

    counts = {}
    for east, north in points:
        cell = _to_cell(east, north, half_extent, width, height)
        if cell is not None:
            counts[cell] = counts.get(cell, 0) + 1

    grid = [[' ' for _ in range(width)] for _ in range(height)]

    if radius_feet > 0:
        _draw_radius_ring(grid, radius_feet, half_extent, width, height)

    if counts:
        max_count = max(counts.values())
        for (row, col), count in counts.items():
            grid[row][col] = _density_char(count, max_count)

    center_cell = _to_cell(0, 0, half_extent, width, height)
    if center_cell is not None:
        grid[center_cell[0]][center_cell[1]] = CENTER_CHAR

    if current is not None:
        current_cell = _to_cell(current[0], current[1], half_extent, width, height)
        if current_cell is not None:
            grid[current_cell[0]][current_cell[1]] = CURRENT_CHAR

    lines = [''.join(row) for row in grid]
    caption = "N up / E right -- radius=%dft -- %d pts -- %s=center %s=radius %s=boat-now" % (
        radius_feet, len(points), CENTER_CHAR, RADIUS_CHAR, CURRENT_CHAR)
    return '\n'.join(lines) + '\n' + caption


def _half_extent(points, radius_feet):
    half_extent = radius_feet * 1.15 if radius_feet > 0 else 50.0
    for east, north in points:
        half_extent = max(half_extent, abs(east) * 1.1, abs(north) * 1.1)
    return half_extent


def _density_char(count, max_count):
    scale = len(DENSITY_CHARS) - 1
    idx = 1 + int((count - 1) / max(1, max_count - 1) * (scale - 1)) if max_count > 1 else 1
    return DENSITY_CHARS[min(scale, idx)]


def _to_cell(east, north, half_extent, width, height):
    col = int((east + half_extent) / (2 * half_extent) * (width - 1) + 0.5)
    row = int((half_extent - north) / (2 * half_extent) * (height - 1) + 0.5)
    if 0 <= row < height and 0 <= col < width:
        return row, col
    return None


def _draw_radius_ring(grid, radius_feet, half_extent, width, height):
    feet_per_col = (2 * half_extent) / (width - 1)
    ring_thickness = feet_per_col * 0.75
    for row in range(height):
        north = half_extent - row / (height - 1) * (2 * half_extent)
        for col in range(width):
            east = col / (width - 1) * (2 * half_extent) - half_extent
            if abs(math.hypot(east, north) - radius_feet) < ring_thickness:
                grid[row][col] = RADIUS_CHAR
