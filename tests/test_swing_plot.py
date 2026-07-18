import unittest

import swing_plot


class SwingPlotTests(unittest.TestCase):
    def test_render_with_no_points_does_not_crash(self):
        output = swing_plot.render([], radius_feet=0, width=11, height=7)
        lines = output.split('\n')
        self.assertEqual(len(lines), 9)  # 7 grid rows + caption + legend line

    def test_grid_dimensions_match_requested_size(self):
        output = swing_plot.render([], radius_feet=50, width=15, height=9)
        lines = output.split('\n')
        grid_lines = lines[:9]
        self.assertEqual(len(grid_lines), 9)
        for line in grid_lines:
            self.assertEqual(len(line), 15)

    def test_center_is_always_marked(self):
        output = swing_plot.render([(10, 10)], radius_feet=50, width=21, height=11)
        self.assertIn(swing_plot.CENTER_CHAR, output)

    def test_zero_radius_skips_drawing_the_ring(self):
        output = swing_plot.render([], radius_feet=0, width=21, height=11)
        grid = '\n'.join(output.split('\n')[:-2])  # drop caption + legend lines
        self.assertNotIn(swing_plot.RADIUS_CHAR, grid)

    def test_positive_radius_draws_a_ring(self):
        output = swing_plot.render([], radius_feet=50, width=41, height=21)
        grid = '\n'.join(output.split('\n')[:-2])  # drop caption + legend lines
        self.assertIn(swing_plot.RADIUS_CHAR, grid)

    def test_point_far_outside_default_extent_does_not_crash(self):
        # half_extent auto-scales to include outlying points instead of
        # indexing off the edge of the grid.
        output = swing_plot.render([(5000, -5000)], radius_feet=50, width=21, height=11)
        self.assertIn(swing_plot.CENTER_CHAR, output)

    def test_repeated_visits_to_the_same_cell_use_a_denser_character(self):
        # Many points clustered in one spot (off-center, so they don't get
        # overwritten by the center marker) should render "denser" than a
        # single point elsewhere.
        clustered = [(20, 20)] * 20
        single = [(-20, -20)]
        output = swing_plot.render(clustered + single, radius_feet=0, width=41, height=21)
        cluster_col = swing_plot._to_cell(20, 20, swing_plot._half_extent(clustered + single, 0), 41, 21)
        single_col = swing_plot._to_cell(-20, -20, swing_plot._half_extent(clustered + single, 0), 41, 21)
        lines = output.split('\n')
        cluster_char = lines[cluster_col[0]][cluster_col[1]]
        single_char = lines[single_col[0]][single_col[1]]
        self.assertGreater(
            swing_plot.DENSITY_CHARS.index(cluster_char),
            swing_plot.DENSITY_CHARS.index(single_char))

    def test_caption_reports_radius_and_point_count(self):
        output = swing_plot.render([(1, 1), (2, 2)], radius_feet=75, width=21, height=11)
        caption = output.split('\n')[-2]  # caption line, before the legend line
        self.assertIn("75ft", caption)
        self.assertIn("2 pts", caption)

    def test_no_current_marker_when_current_is_not_given(self):
        output = swing_plot.render([(20, 20)], radius_feet=0, width=41, height=21)
        grid = '\n'.join(output.split('\n')[:-2])  # drop caption + legend lines
        self.assertNotIn(swing_plot.CURRENT_CHAR, grid)

    def test_current_position_is_marked_distinctly_from_history(self):
        # A trail of old points plus one current point at a different spot --
        # the current spot should show CURRENT_CHAR, not a density character.
        history = [(20, 20)] * 10
        current = (-20, -20)
        points = history + [current]
        output = swing_plot.render(points, radius_feet=0, width=41, height=21, current=current)
        half_extent = swing_plot._half_extent(points, 0)
        current_cell = swing_plot._to_cell(current[0], current[1], half_extent, 41, 21)
        lines = output.split('\n')
        self.assertEqual(lines[current_cell[0]][current_cell[1]], swing_plot.CURRENT_CHAR)

    def test_current_marker_takes_priority_over_center_marker(self):
        # If the boat is currently sitting right on top of center, knowing
        # "that's where I am right now" matters more than the center mark.
        output = swing_plot.render([(0, 0)], radius_feet=0, width=21, height=11, current=(0, 0))
        half_extent = swing_plot._half_extent([(0, 0)], 0)
        cell = swing_plot._to_cell(0, 0, half_extent, 21, 11)
        lines = output.split('\n')
        self.assertEqual(lines[cell[0]][cell[1]], swing_plot.CURRENT_CHAR)

    def test_caption_documents_the_current_marker(self):
        output = swing_plot.render([(1, 1)], radius_feet=50, width=21, height=11, current=(1, 1))
        legend = output.split('\n')[-1]
        self.assertIn("%s=boat-now" % swing_plot.CURRENT_CHAR, legend)

    def test_legend_documents_the_density_gradient(self):
        # Regression test: the density characters used to shade the grid
        # were never explained anywhere in the output, leaving no way to
        # tell what a low-density char vs a high-density char meant.
        output = swing_plot.render([(1, 1)], radius_feet=50, width=21, height=11)
        legend = output.split('\n')[-1]
        self.assertIn(swing_plot.DENSITY_CHARS[1:], legend)

    def test_center_char_is_never_reused_in_the_density_ramp(self):
        # Regression test: CENTER_CHAR used to be '+', which also appeared
        # partway through the density ramp -- a cell could be ambiguous
        # between "this is center" and "this is a moderately-visited cell".
        self.assertNotIn(swing_plot.CENTER_CHAR, swing_plot.DENSITY_CHARS)

    def test_no_error_marker_when_error_feet_not_given(self):
        output = swing_plot.render([], radius_feet=50, width=41, height=21, current=(20, 20))
        grid = '\n'.join(output.split('\n')[:-2])
        self.assertNotIn(swing_plot.ERROR_CHAR, grid)

    def test_no_error_marker_when_current_not_given(self):
        output = swing_plot.render([], radius_feet=50, width=41, height=21, error_feet=20)
        grid = '\n'.join(output.split('\n')[:-2])
        self.assertNotIn(swing_plot.ERROR_CHAR, grid)

    def test_worst_case_point_is_on_the_same_bearing_past_current(self):
        # 40ft due east of center, with 10ft of error -> worst case is
        # 50ft due east: same bearing, current distance + error.
        east, north = swing_plot.worst_case_point((40, 0), 10)
        self.assertAlmostEqual(east, 50)
        self.assertAlmostEqual(north, 0)

    def test_worst_case_point_is_none_when_boat_is_exactly_at_center(self):
        # No defined bearing to project the error along.
        self.assertIsNone(swing_plot.worst_case_point((0, 0), 10))

    def test_worst_case_point_is_none_without_current_or_error(self):
        self.assertIsNone(swing_plot.worst_case_point(None, 10))
        self.assertIsNone(swing_plot.worst_case_point((40, 0), None))

    def test_error_marker_is_drawn_at_the_worst_case_point(self):
        current = (40, 0)
        output = swing_plot.render([current], radius_feet=100, width=61, height=31,
                                    current=current, error_feet=10)
        half_extent = swing_plot._half_extent([current], 100, swing_plot.worst_case_point(current, 10))
        worst_cell = swing_plot._to_cell(50, 0, half_extent, 61, 31)
        lines = output.split('\n')
        self.assertEqual(lines[worst_cell[0]][worst_cell[1]], swing_plot.ERROR_CHAR)

    def test_current_marker_wins_when_error_is_zero(self):
        # error_feet=0 puts the worst-case point at the exact same spot as
        # current -- current should still win there, not get hidden by 'e'.
        current = (40, 0)
        output = swing_plot.render([current], radius_feet=100, width=41, height=21,
                                    current=current, error_feet=0)
        half_extent = swing_plot._half_extent([current], 100, swing_plot.worst_case_point(current, 0))
        cell = swing_plot._to_cell(40, 0, half_extent, 41, 21)
        lines = output.split('\n')
        self.assertEqual(lines[cell[0]][cell[1]], swing_plot.CURRENT_CHAR)

    def test_caption_reports_gps_error_when_given(self):
        output = swing_plot.render([], radius_feet=100, width=21, height=11,
                                    current=(40, 0), error_feet=35)
        caption = output.split('\n')[-2]
        self.assertIn("radius=100ft", caption)
        self.assertIn("GPS error=35ft", caption)

    def test_legend_documents_the_worst_case_marker(self):
        output = swing_plot.render([], radius_feet=100, width=21, height=11,
                                    current=(40, 0), error_feet=35)
        legend = output.split('\n')[-1]
        self.assertIn("%s=worst-case" % swing_plot.ERROR_CHAR, legend)

    def test_no_alarm_marker_when_alarm_points_not_given(self):
        output = swing_plot.render([], radius_feet=50, width=41, height=21)
        grid = '\n'.join(output.split('\n')[:-2])
        self.assertNotIn(swing_plot.ALARM_CHAR, grid)

    def test_alarm_points_are_marked_on_the_grid(self):
        alarm_points = [(20, 20)]
        output = swing_plot.render([], radius_feet=0, width=41, height=21, alarm_points=alarm_points)
        half_extent = swing_plot._half_extent([], 0, alarm_points=alarm_points)
        cell = swing_plot._to_cell(20, 20, half_extent, 41, 21)
        lines = output.split('\n')
        self.assertEqual(lines[cell[0]][cell[1]], swing_plot.ALARM_CHAR)

    def test_alarm_points_do_not_require_current_history_points(self):
        # Regression: alarm_points is a separate, caller-managed record --
        # rendering it shouldn't depend on points (the rolling window) also
        # containing those same positions.
        output = swing_plot.render([], radius_feet=0, width=41, height=21, alarm_points=[(20, 20), (-20, -20)])
        grid = '\n'.join(output.split('\n')[:-2])
        self.assertEqual(grid.count(swing_plot.ALARM_CHAR), 2)

    def test_current_marker_wins_over_alarm_marker_at_the_same_cell(self):
        output = swing_plot.render([], radius_feet=0, width=41, height=21,
                                    current=(20, 20), alarm_points=[(20, 20)])
        half_extent = swing_plot._half_extent([], 0, alarm_points=[(20, 20)])
        cell = swing_plot._to_cell(20, 20, half_extent, 41, 21)
        lines = output.split('\n')
        self.assertEqual(lines[cell[0]][cell[1]], swing_plot.CURRENT_CHAR)

    def test_caption_reports_alarm_point_count(self):
        output = swing_plot.render([], radius_feet=50, width=21, height=11,
                                    alarm_points=[(1, 1), (2, 2), (3, 3)])
        caption = output.split('\n')[-2]
        self.assertIn("3 alarm pts", caption)

    def test_legend_documents_the_alarm_marker(self):
        output = swing_plot.render([], radius_feet=50, width=21, height=11)
        legend = output.split('\n')[-1]
        self.assertIn("%s=alarm sounded" % swing_plot.ALARM_CHAR, legend)


if __name__ == '__main__':
    unittest.main()
