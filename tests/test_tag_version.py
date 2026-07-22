import unittest

from tools.check_tag_version import check_tag, package_version


class TagVersionTests(unittest.TestCase):
    def test_exact_prerelease_tag_is_required(self):
        version = package_version()
        self.assertEqual(check_tag("v" + version), [])
        self.assertTrue(check_tag("v0.11.0"))
        self.assertTrue(check_tag("0.11.0b1"))


if __name__ == "__main__":
    unittest.main()
