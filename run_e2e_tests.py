import os
import sys

import pytest

def run_suite():
    # Insert root workspace directory to sys.path
    root_dir = os.path.dirname(os.path.abspath(__file__))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    print("Running the complete OmniVLA pytest suite...")
    # pytest is the canonical runner: the suite contains both unittest classes
    # and pytest-style function tests for the command center and security policy.
    raise SystemExit(pytest.main([os.path.join(root_dir, "tests"), "-ra"]))

if __name__ == "__main__":
    run_suite()
