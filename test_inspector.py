# -*- coding: utf-8 -*-
"""Offline parser and generated Python code checks (no Swing required)."""
import unittest
from swing_inspector import ControlRecord, add_duplicate_info, locator_code, parse_console_log


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


if __name__ == '__main__':
    unittest.main()
