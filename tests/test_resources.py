import hashlib
from importlib.resources import files
import unittest

from ssdbench.resources import load_profile, source_hashes


class PackagedResources(unittest.TestCase):
    def test_both_profiles_load_from_package(self):
        for name in ('screen', 'full'):
            profile = load_profile(name)
            self.assertEqual(profile['mode'], name)
            self.assertGreater(profile['seconds'], 0)

    def test_unknown_profile_rejected(self):
        with self.assertRaises(ValueError):
            load_profile('../outside')

    def test_manifest_hashes_cover_installed_code_and_profiles(self):
        hashes = source_hashes()
        for name in ('runner.py', 'resources.py', 'profiles/full.json', 'profiles/screen.json'):
            expected = hashlib.sha256(files('ssdbench').joinpath(name).read_bytes()).hexdigest()
            self.assertEqual(hashes['ssdbench/' + name], expected)


if __name__ == '__main__':
    unittest.main()
