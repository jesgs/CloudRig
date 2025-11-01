@echo off
setlocal

for %%B in (
    "D:\3D\Blender\5.0 Beta"
    "D:\3D\Blender\4.5"
) do (
    echo ================================
    echo Running all tests on Blender at %%~B
    "%%~B\blender.exe" --background --python "run_all_tests.py"
)

pause
