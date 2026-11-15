"""The website's built files: small facts that have broken a release without anything else noticing."""

import json
import re
import unittest
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"


class WebAppTests(unittest.TestCase):
    def test_the_web_app_is_built_for_the_folder_it_is_served_from(self):
        # built without --base-href /write/ the page asks the site root for its script and never starts
        page = (SITE / "write" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<base href="/write/">', page)

    def test_the_download_the_front_page_links_is_the_one_whose_checksum_is_printed(self):
        front = (SITE / "index.html").read_text(encoding="utf-8")
        linked = set(re.findall(r'href="app/(berrychain-wallet-[0-9.]+\.apk)"', front))
        self.assertEqual(len(linked), 1, linked)
        name = linked.pop()
        self.assertTrue((SITE / "app" / name).is_file(), name)
        self.assertIn("*" + name, (SITE / "app" / "SHA256.txt").read_text(encoding="utf-8"))

    def test_the_web_app_and_the_download_are_the_same_version(self):
        front = (SITE / "index.html").read_text(encoding="utf-8")
        apk = re.search(r'href="app/berrychain-wallet-([0-9.]+)\.apk"', front).group(1)
        web = json.loads((SITE / "write" / "version.json").read_text(encoding="utf-8"))["version"]
        self.assertEqual(apk, web)


if __name__ == "__main__":
    unittest.main()
