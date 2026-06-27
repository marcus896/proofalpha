from __future__ import annotations

import unittest
from pathlib import Path


class OfficialDocsReviewTests(unittest.TestCase):
    def test_binance_and_mcp_review_files_exist(self) -> None:
        for name in ("binance_usdm_api_review.md", "mcp_tools_security_review.md"):
            with self.subTest(name=name):
                self.assertTrue((Path("docs/references") / name).exists())

    def test_reviews_record_required_safety_points(self) -> None:
        binance = Path("docs/references/binance_usdm_api_review.md").read_text(encoding="utf-8")
        mcp = Path("docs/references/mcp_tools_security_review.md").read_text(encoding="utf-8")

        self.assertIn("PRICE_FILTER", binance)
        self.assertIn("LOT_SIZE", binance)
        self.assertIn("reduceOnly", binance)
        self.assertIn("newClientOrderId", binance)
        self.assertIn("tools/list", mcp)
        self.assertIn("tools/call", mcp)
        self.assertIn("human in the loop", mcp)
        self.assertIn("forbidden tool list", mcp)


if __name__ == "__main__":
    unittest.main()
