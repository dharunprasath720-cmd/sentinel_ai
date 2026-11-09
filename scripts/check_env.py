"""Print the Python version and the version of every dependency."""
import importlib
import sys

PACKAGES = ["pandas", "numpy", "sklearn", "lightgbm", "shap", "sqlalchemy",
            "pydantic", "pydantic_settings", "joblib", "pytest", "networkx", "yaml",
            "argon2", "jwt", "fastapi", "httpx", "uvicorn"]

print("python", sys.version.split()[0])
failed = []
for name in PACKAGES:
    try:
        mod = importlib.import_module(name)
        print(f"{name:20s} {getattr(mod, '__version__', '?')}")
    except Exception as exc:  # noqa: BLE001
        failed.append(name)
        print(f"{name:20s} FAILED: {exc}")
sys.exit(1 if failed else 0)
