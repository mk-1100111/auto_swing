# -*- coding: utf-8 -*-
"""Offline parser and generated Python code checks (no Swing required)."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from swing_inspector import (ControlRecord, Inspector, add_duplicate_info,
                             locator_code, parse_console_log, rectangle_center)


class InspectorTests(unittest.TestCase):
    def test_parse_log(self):
        result = parse_console_log(
            '[Button      ] ID=btn_search                                                   TEXT=조회\n'
            '[Edit        ] ID=cal_sta_dt_input                                             TEXT=2026-10-13\n'
            '[Text        ] ID=                                                             TEXT=고객명\n'
        )
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].auto_id, 'btn_search')
        self.assertEqual(result[0].name, '조회')
        self.assertEqual(result[2].auto_id, '')

    def test_duplicate_blank_ids(self):
        rows = add_duplicate_info([
            ControlRecord(1, 'Text', name='2026-10-13'),
            ControlRecord(2, 'Edit', auto_id='cal_sta_dt_input', name='2026-10-13'),
            ControlRecord(3, 'Text', name='2026-10-13'),
        ])
        self.assertEqual(rows[2].match_index, 1)
        self.assertEqual(rows[2].match_count, 2)
        code = locator_code(rows[2])
        self.assertIn('candidates[1]', code)
        self.assertIn("automation_id or ''", code)
        compile(code, 'generated', 'exec')

    def test_code_templates(self):
        item = ControlRecord(1, 'Edit', auto_id='abc', name='샘플')
        for action in ('find', 'click', 'input'):
            compile(locator_code(item, action=action), 'generated', 'exec')
        self.assertIn("target.set_edit_text('입력할 값')", locator_code(item, action='input'))
        self.assertIn('target.click_input()', locator_code(item, action='click'))


    def test_rectangle_center(self):
        self.assertEqual(rectangle_center("100, 200, 300, 400"), (200, 300))
        self.assertEqual(rectangle_center("-900, -100, -700, -40"), (-800, -70))
        self.assertEqual(rectangle_center("0, 0, 1, 1"), (0, 0))

    def test_invalid_rectangle_no_movement(self):
        for rect in ("", "(100,200)", "2, 3, 2, 9", "0, 0, 4, 0", "a, 1, 2, 3", "1,2,3"):
            self.assertIsNone(rectangle_center(rect))
        item = ControlRecord(1, "Button", auto_id="abc", source="TXT 로그")
        fake = SimpleNamespace(_selected=lambda: item, status_var=SimpleNamespace(set=lambda x: None))
        with patch("swing_inspector.move_cursor") as move:
            Inspector.move_to_selected_coordinates(fake)
            move.assert_not_called()

    def test_coordinate_double_click_only_in_last_column(self):
        selected = []
        fake_tree = SimpleNamespace(
            identify_row=lambda y: "control-1",
            identify_region=lambda x, y: "cell",
            identify_column=lambda x: "#5" if x == 5 else "#3",
            selection_set=selected.append,
            focus=lambda x: None,
        )
        fake = SimpleNamespace(tree=fake_tree, displayed={"control-1": ControlRecord(1,"Button",rect="100,200,200,300")},
                               move_to_selected_coordinates=lambda: selected.append("moved"),
                               copy_field=lambda field: selected.append(field))
        self.assertEqual(Inspector._tree_double_click(fake, SimpleNamespace(x=5,y=10)), "break")
        self.assertEqual(selected[-1], "moved")
        self.assertEqual(Inspector._tree_double_click(fake, SimpleNamespace(x=3,y=10)), "break")
        self.assertEqual(selected[-1], "auto_id")

    def test_move_to_center(self):
        item = ControlRecord(1, "Button", auto_id="abc", rect="100, 200, 300, 500")
        out = []
        fake = SimpleNamespace(_selected=lambda: item, status_var=SimpleNamespace(set=out.append))
        with patch("swing_inspector.move_cursor") as move:
            Inspector.move_to_selected_coordinates(fake)
            move.assert_called_once_with(200,350)
        self.assertIn("이동 완료",out[-1])


if __name__ == '__main__':
    unittest.main()
