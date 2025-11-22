# How to run tests

Tests require [Blender as Python Module](https://pypi.org/project/bpy/) which in turn currently requires Python 3.11 and not higher.

1. **Install Python 3.11**  
    This differs for every system so, figure it out.
1. **Creating Python virtual environment in the repo's root**  
    `cd some/path/CloudRig`  
    `python3.11 -m venv .venv`
1. **Activate Python 3.11 venv**  
    `. .venv/bin/activate`
1. **Install dependencies**  
    `pip install requirements-dev.txt`
1. **Run tests**  
    `pytest`
1. **Run tests with coverage stats**  
    `pip install coverage pytest-cov`  
    `pytest --cov=CloudRig`