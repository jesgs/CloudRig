# How to run tests

Tests require [Blender as Python Module](https://pypi.org/project/bpy/) which in turn currently requires Python 3.11 and not higher.

1. **Install Python 3.11**  
    Windows: Download & install from https://www.python.org/downloads/release/python-3117/
    Other OS: Figure it out.
1. **Creating Python virtual environment in the repo's root**  
    `cd path/to/CloudRig`  
    Windows: `py -3.11 -m venv .venv`
    Linux: `python3.11 -m venv .venv`
1. **Activate Python 3.11 venv**  
    Windows: `.\.venv\Scripts\activate`
    Linux: `. .venv/bin/activate`
1. **Install dependencies**  
    `pip install -r requirements-dev.txt`
1. **Run (verbose) tests**  
    `pytest -v`
1. **Run tests with coverage visualization**  
    `pip install coverage pytest-cov`  
    `pytest -v --durations=0 --cov=./CloudRig --cov-report=html --cov-branch`
    Durations of test executions will be printed in the terminal.
    Coverage stats can be seen by opening `htmlcov/index.html` file in a web browser.

# Contribute
You can see a list of desired tests [here](https://projects.blender.org/Mets/CloudRig/issues/242). To be able to help implement them, you just need to be able to run the tests locally using the instructions above, then learn a bit about the [pytest](https://docs.pytest.org/en/stable/) module.
