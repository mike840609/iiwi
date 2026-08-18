import ast
from pathlib import Path

HARNESSES = Path("src/iiwi/harnesses")
FORBIDDEN = "iiwi.summarizers"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_harnesses_do_not_import_summarizers() -> None:
    """Reading sessions must stay replaceable without touching narration.

    A violation has no symptom at run time; it only shows up when someone tries
    to swap the narration layer, which is exactly when it is expensive to find.
    """

    offenders = {
        str(path): sorted(
            module
            for module in _imported_modules(path)
            if module == FORBIDDEN or module.startswith(f"{FORBIDDEN}.")
        )
        for path in sorted(HARNESSES.rglob("*.py"))
    }
    offenders = {path: modules for path, modules in offenders.items() if modules}

    assert offenders == {}
