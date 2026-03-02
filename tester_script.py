import unittest
from tests import (
    thread_rwlock_test, 
    async_rwlock_test, 
    thread_rwcondition_test,
    async_rwcondition_test
)

def run_all_tests():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(thread_rwlock_test)
    suite.addTests(loader.loadTestsFromModule(async_rwlock_test))
    suite.addTests(loader.loadTestsFromModule(thread_rwcondition_test))
    suite.addTests(loader.loadTestsFromModule(async_rwcondition_test))

    runner = unittest.TextTestRunner(verbosity=2)
    
    print("--- RWLock Start Test ---")
    result = runner.run(suite)
    
    return result.wasSuccessful()

if __name__ == '__main__':
    is_success = run_all_tests()
    if not is_success:
        exit(1)