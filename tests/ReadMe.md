# How to run tests

Tests require [Blender as Python Module](https://pypi.org/project/bpy/) which in turn currently requires Python 3.11 and not higher.

**Install Python 3.11**
This differs for every system so, figure it out.

**Creating Python virtual environment in the repo's root**
```
cd some/path/CloudRig
python3.11 -m venv .venv
```

**Activate Python 3.11 venv**
`. .venv/bin/activate`

**Install Blender as Python Module**
`pip install bpy==5.0.0`

**Run all tests as Python module (-m)**
`python -m tests.run_all_tests`