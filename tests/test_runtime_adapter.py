from __future__ import annotations

import unittest

from proofalpha.runtime import packaged_skills_dir


class RuntimeAdapterTests(unittest.TestCase):
    def test_packaged_skills_are_present(self) -> None:
        self.assertEqual(len(list(packaged_skills_dir().glob("*/SKILL.md"))), 6)


if __name__ == "__main__":
    unittest.main()
