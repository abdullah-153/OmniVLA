import unittest
import sys
import os

def run_suite():
    # Insert root workspace directory to sys.path
    root_dir = os.path.dirname(os.path.abspath(__file__))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    print("====================================================")
    print("Running Holo3.1 E2E Test Suite...")
    print("====================================================")

    # Discover and run tests
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=os.path.join(root_dir, "tests"), pattern="test_*.py")
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n====================================================")
    print("Test Results Summary:")
    print("====================================================")
    print(f"Total Tests Run: {result.testsRun}")
    print(f"Passed: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failed: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("====================================================")
    
    if not result.wasSuccessful():
        print("FAIL: E2E tests failed.")
        sys.exit(1)
    else:
        print("SUCCESS: All E2E tests passed!")
        sys.exit(0)

if __name__ == "__main__":
    run_suite()
