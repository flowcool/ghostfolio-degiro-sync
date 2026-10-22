"""Enforce mechanical conventions through the existing offline pytest CI."""

import ast
from pathlib import Path

import pytest


def convention_violations(source, typed=False):
    tree = ast.parse(source, type_comments=True)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            frozen = any(isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name) and decorator.func.id == 'dataclass'
                and any(keyword.arg == 'frozen' and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True for keyword in decorator.keywords)
                for decorator in node.decorator_list)
            record = any(isinstance(base, ast.Name) and base.id == 'TypedDict' for base in node.bases)
            if not typed or not (frozen or record):
                violations.append((node.lineno, 'class definition'))
            elif any(isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) for child in node.body):
                violations.append((node.lineno, 'business method in data record'))
        elif not typed and isinstance(node, ast.AnnAssign):
            violations.append((node.lineno, 'variable annotation'))
        elif not typed and isinstance(node, ast.arg) and node.annotation is not None:
            violations.append((node.lineno, 'argument annotation'))
        elif not typed and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            violations.append((node.lineno, 'return annotation'))
        if getattr(node, 'type_comment', None) is not None or isinstance(node, ast.TypeIgnore):
            violations.append((node.lineno, 'type comment'))
        if not typed and (getattr(node, 'type_params', ()) or type(node).__name__ == 'TypeAlias'):
            violations.append((node.lineno, 'type parameter or alias'))
    return sorted(set(violations))


def test_all_project_python_obeys_functional_unannotated_style():
    root = Path(__file__).resolve().parents[1]
    # Include the frozen core and fixture projection read-only, never rewrite them.
    files = sorted(set(root.glob('*.py')) | set((root / 'scripts').rglob('*.py'))
        | set((root / 'tests').rglob('*.py'))
        | set((root / 'ghostfolio_degiro_sync').rglob('*.py')))
    names = {str(path.relative_to(root)) for path in files}
    assert {'degiro_to_ghostfolio.py', 'ghostfolio_core.py', 'scripts/merge_pr.py',
        'tests/test_python_conventions.py'} <= names
    failures = [(str(path.relative_to(root)), line, reason) for path in files
        for line, reason in convention_violations(path.read_text(encoding="utf-8"),
            typed='ghostfolio_degiro_sync' in path.parts or path.name == 'ghostfolio_core.py')]
    assert not failures, failures


@pytest.mark.parametrize('source', ['class Client: pass',
    'def f(x: int): pass', 'def f(*x: int): pass', 'def f(**x: int): pass',
    'def f() -> int: return 1', 'async def f() -> int: return 1',
    'x: int = 1', 'x = 1 # type: int', 'x = 1 # type: ignore',
    'def f(x): # type: (int) -> int\n return x'])
def test_guard_rejects_mechanical_violations(source):
    assert convention_violations(source)


def test_plain_functions_and_annotation_words_in_strings_are_allowed():
    assert convention_violations('def f(x):\n return "class C: x: int"') == []


@pytest.mark.skipif(not hasattr(ast, 'TypeAlias'), reason='PEP 695 requires Python 3.12')
@pytest.mark.parametrize('source', ['type Value = int', 'def f[T](x): return x'])
def test_python_312_typing_constructs_are_rejected(source):
    assert convention_violations(source)
