# How to run tests

Tests require [Blender as Python Module](https://pypi.org/project/bpy/) which in turn currently requires Python 3.11 and not higher.

1. **Install Python 3.11**  
    This differs for every system so, figure it out.
1. **Creating Python virtual environment in the repo's root**  
    `cd path/to/CloudRig`  
    `python3.11 -m venv .venv`
1. **Activate Python 3.11 venv**  
    `. .venv/bin/activate`
1. **Install dependencies**  
    `pip install requirements-dev.txt`
1. **Run (verbose) tests**  
    `pytest -v`
1. **Run tests with coverage stats (not super meaningful tbh)**  
    `pip install coverage pytest-cov`  
    `pytest --cov=CloudRig`

# Contribute
You can see a list of desired tests [here](https://projects.blender.org/Mets/CloudRig/issues/242). To be able to help implement them, you just need to be able to run the tests locally using the instructions above, then learn a bit about the [pytest](https://docs.pytest.org/en/stable/) module.
