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
# index 0 is reserved for "no points here". '.' is deliberately excluded:
# it sits low in the character cell rather than centered, so it reads
# inconsistently against the rest of the (vertically centered) ramp.
DENSITY_CHARS = " :-=+*#%@"

CENTER_CHAR = 'X'  # reserved for center -- never reused in the density ramp
RADIUS_CHAR = 'o'
ERROR_CHAR = 'e'  # worst-case position given current GPS error
ALARM_CHAR = 'a'  # a position where the alarm was actively sounding due to distance
SPEED_ALARM_CHAR = 's'  # a position where the alarm was actively sounding due to speed
CURRENT_CHAR = 'B'  # current boat position -- always drawn on top of everything else


def render(points, radius_feet, width=WIDTH, height=HEIGHT, current=None, error_feet=None,
           alarm_points=None, speed_alarm_points=None):
    """points: iterable of (east_feet, north_feet) offsets from center.

    current: the boat's current position, as an (east_feet, north_feet)
    tuple, marked distinctly (CURRENT_CHAR) on top of the history/center/
    radius markers -- otherwise the most recent position looks like just
    another history point. If given, it should normally already be one of
    the entries in points (e.g. the last one), so the auto-scaling below
    accounts for it; passing a point outside the range of points may place
    it off the edge of the visible plot.

    error_feet: current GPS position error (AlarmState.pos_error), in
    feet. If given along with current, a single point (ERROR_CHAR) is
    drawn on the same bearing from center as the current position, at
    distance a+error_feet where a is the current distance from center --
    i.e. "worst case, given today's GPS uncertainty, the boat could really
    be out here." Comparing that point against the radius ring makes it
    obvious at a glance whether GPS error alone could be putting you past
    the limit, without needing a whole second ring. Skipped if current is
    None, error_feet is None, or the boat is currently sitting exactly at
    center (no bearing to project along).

    alarm_points: iterable of (east_feet, north_feet) worst-case offsets
    recorded at every tick the alarm was actively sounding due to distance,
    marked with ALARM_CHAR.

    speed_alarm_points: iterable of (east_feet, north_feet) offsets
    recorded at every tick the alarm was actively sounding due to speed,
    marked with SPEED_ALARM_CHAR. Unlike alarm_points, these are the raw
    current position, not a worst-case-adjusted one -- GPS position error
    doesn't have the same "worst case" relationship to a speed threshold
    that it does to a distance threshold, so there's nothing to adjust for.

    Both alarm_points and speed_alarm_points are meant to be unbounded,
    caller-managed records that persist until explicitly cleared (unlike
    points, a rolling recent-history window), so past alarm episodes stay
    visible across the session.

    Returns a multi-line string: a width x height character grid with the
    center marked, the current alarm radius circle overlaid, recent points
    density-shaded by how often each cell was visited, and the current
    position marked distinctly, followed by a caption line and a legend
    line spelling out what each marker/density character means.
    """
    points = list(points)
    alarm_points = list(alarm_points) if alarm_points is not None else []
    speed_alarm_points = list(speed_alarm_points) if speed_alarm_points is not None else []
    worst_case = worst_case_point(current, error_feet)
    half_extent = _half_extent(points, radius_feet, worst_case, alarm_points + speed_alarm_points)

    counts = {}
    for east, north in points:
        cell = _to_cell(east, north, half_extent, width, height)
        if cell is not None:
            counts[cell] = counts.get(cell, 0) + 1

    grid = [[' ' for _ in range(width)] for _ in range(height)]

    if radius_feet > 0:
        _draw_radius_ring(grid, radius_feet, half_extent, width, height, RADIUS_CHAR)

    if counts:
        max_count = max(counts.values())
        for (row, col), count in counts.items():
            grid[row][col] = _density_char(count, max_count)

    for east, north in alarm_points:
        cell = _to_cell(east, north, half_extent, width, height)
        if cell is not None:
            grid[cell[0]][cell[1]] = ALARM_CHAR

    for east, north in speed_alarm_points:
        cell = _to_cell(east, north, half_extent, width, height)
        if cell is not None:
            grid[cell[0]][cell[1]] = SPEED_ALARM_CHAR

    center_cell = _to_cell(0, 0, half_extent, width, height)
    if center_cell is not None:
        grid[center_cell[0]][center_cell[1]] = CENTER_CHAR

    if worst_case is not None:
        worst_cell = _to_cell(worst_case[0], worst_case[1], half_extent, width, height)
        if worst_cell is not None:
            grid[worst_cell[0]][worst_cell[1]] = ERROR_CHAR

    if current is not None:
        current_cell = _to_cell(current[0], current[1], half_extent, width, height)
        if current_cell is not None:
            grid[current_cell[0]][current_cell[1]] = CURRENT_CHAR

    lines = [''.join(row) for row in grid]
    counts_suffix = "%d pts, %d alarm pts, %d speed-alarm pts" % (
        len(points), len(alarm_points), len(speed_alarm_points))
    if error_feet is not None:
        caption = "N up / E right -- radius=%dft, GPS error=%dft -- %s" % (
            radius_feet, error_feet, counts_suffix)
    else:
        caption = "N up / E right -- radius=%dft -- %s" % (radius_feet, counts_suffix)
    legend = ("%s=center  %s=radius  %s=worst-case (current+error)  %s=alarm sounded (distance)  "
              "%s=alarm sounded (speed)  %s=boat-now  |  density, rarely..often visited: %s") % (
        CENTER_CHAR, RADIUS_CHAR, ERROR_CHAR, ALARM_CHAR, SPEED_ALARM_CHAR, CURRENT_CHAR,
        DENSITY_CHARS[1:])
    return '\n'.join(lines) + '\n' + caption + '\n' + legend


def worst_case_point(current, error_feet):
    if current is None or error_feet is None:
        return None
    distance = math.hypot(current[0], current[1])
    if distance <= 0:
        return None  # no defined bearing to project the error along
    scale = (distance + error_feet) / distance
    return current[0] * scale, current[1] * scale


def _half_extent(points, radius_feet, worst_case=None, alarm_points=None):
    half_extent = radius_feet * 1.15 if radius_feet > 0 else 50.0
    for east, north in points:
        half_extent = max(half_extent, abs(east) * 1.1, abs(north) * 1.1)
    if worst_case is not None:
        half_extent = max(half_extent, abs(worst_case[0]) * 1.1, abs(worst_case[1]) * 1.1)
    for east, north in (alarm_points or []):
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


def _draw_radius_ring(grid, radius_feet, half_extent, width, height, char):
    feet_per_col = (2 * half_extent) / (width - 1)
    ring_thickness = feet_per_col * 0.75
    for row in range(height):
        north = half_extent - row / (height - 1) * (2 * half_extent)
        for col in range(width):
            east = col / (width - 1) * (2 * half_extent) - half_extent
            if abs(math.hypot(east, north) - radius_feet) < ring_thickness:
                grid[row][col] = char
