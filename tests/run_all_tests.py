import os
import traceback

# Directory of this script
tests_dir = os.path.dirname(__file__)
this_file = os.path.basename(__file__)

# Collect all Python test files in the folder, excluding this one
test_files = sorted(
    f for f in os.listdir(tests_dir)
    if f.endswith(".py") and f != this_file
)

print(f"Running tests: {', '.join(test_files)}")

# Run each test
for test in test_files:
    path = os.path.join(tests_dir, test)
    print(f"\n--- Running {test} ---")
    try:
        with open(path, "r") as f:
            exec(f.read(), {"__name__": "__main__"})
        print(f"{test} completed successfully.")
    except Exception:
        print(f"ERROR in {test}:")
        traceback.print_exc()
