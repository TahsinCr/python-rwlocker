import subprocess
import sys
import unittest


class PackageImportIsolationTests(unittest.TestCase):
    def test_thread_import_does_not_load_async_implementation(self):
        code = (
            "import sys, rwlocker; "
            "assert 'rwlocker.thread_rwlock' not in sys.modules; "
            "assert 'rwlocker.async_rwlock' not in sys.modules; "
            "from rwlocker import RWLockWrite; "
            "assert 'rwlocker.thread_rwlock' in sys.modules; "
            "assert 'rwlocker.async_rwlock' not in sys.modules"
        )
        subprocess.run([sys.executable, "-c", code], check=True)

    def test_async_import_does_not_load_thread_implementation(self):
        code = (
            "import sys, rwlocker; "
            "assert 'rwlocker.thread_rwlock' not in sys.modules; "
            "assert 'rwlocker.async_rwlock' not in sys.modules; "
            "from rwlocker import AsyncRWLockWrite; "
            "assert 'rwlocker.async_rwlock' in sys.modules; "
            "assert 'rwlocker.thread_rwlock' not in sys.modules"
        )
        subprocess.run([sys.executable, "-c", code], check=True)


if __name__ == "__main__":
    unittest.main()
