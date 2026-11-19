# pytest idioms

Each idiom links to the official docs. Before relying on an idiom, check it against the pytest version the repository pins (`pytest --version`), and look up anything not listed here.

## Contents

- [Test anatomy](#test-anatomy)
- [Factories as fixtures](#factories-as-fixtures)
- [Parametrize with readable ids](#parametrize-with-readable-ids)
- [Parametrized fixtures: one contract, several entry points](#parametrized-fixtures-one-contract-several-entry-points)
- [Exceptions](#exceptions)
- [Known defects: strict xfail](#known-defects-strict-xfail)
- [Boundaries: monkeypatch, tmp_path, the clock](#boundaries-monkeypatch-tmp_path-the-clock)
- [Test classes](#test-classes)
- [factory_boy](#factory_boy)

## Test anatomy

A test has four steps: Arrange, Act, Assert, Cleanup. "At its core, the test is ultimately the act and assert steps." Keep one Act per test and separate the steps with blank lines.
<https://docs.pytest.org/en/stable/explanation/anatomy.html>

## Factories as fixtures

When a test needs several variations of an object, the fixture returns a function that builds it instead of the object itself.
<https://docs.pytest.org/en/stable/how-to/fixtures.html#factories-as-fixtures>

```python
@pytest.fixture
def make_tool():
    def _make_tool(name, filename=None):
        def search(query: str) -> str:
            return ""

        tool = FunctionTool.from_defaults(fn=search, name=name, description=f"Searches {name}.")
        if filename:
            tool.metadata.filename = filename  # mirrors how production attaches the file
        return tool

    return _make_tool
```

## Parametrize with readable ids

Use `pytest.param(..., id="...")` so a failure names the case.
<https://docs.pytest.org/en/stable/how-to/parametrize.html>

```python
@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        pytest.param({"model": "no-such-model"}, "unknown model", id="unknown-model"),
        pytest.param({"reasoning_effort": "minimal"}, "minimal reasoning effort", id="minimal-effort"),
    ],
)
def test_rejects_a_model_setting_the_provider_cannot_serve(build_agent, stored_config, overrides, match):
    stored_config.config.update(overrides)

    with pytest.raises(ValueError, match=match):
        build_agent(stored_config)
```

The docs warn that parameter values are passed as is and not copied: if a test mutates a list or dict parameter, the next case sees the change. Mutate fixture data instead, since fixtures are rebuilt for each test.

## Parametrized fixtures: one contract, several entry points

```python
@pytest.fixture(params=[build_with_constructor, build_with_from_dict], ids=["constructor", "from_dict"])
def build_agent(request):
    return request.param
```

Every test that requests `build_agent` runs once per entry point. Parametrize over functions rather than string tags, so the fixture needs no `if`/`else`.
<https://docs.pytest.org/en/stable/how-to/fixtures.html#parametrizing-fixtures>

## Exceptions

- `pytest.raises(Type, match=r"...")`. `match` uses `re.search`, so escape regex special characters or use `re.escape`.
- `pytest.raises` also accepts subclasses. To require the exact type, check `excinfo.type is Type`.
<https://docs.pytest.org/en/stable/how-to/assert.html#assertions-about-expected-exceptions>

## Known defects: strict xfail

```python
@pytest.mark.xfail(
    strict=True,
    raises=ValueError,
    reason="Known defect: from_dict passes None for omitted options (Unsupported LLM type: None).",
)
def test_from_dict_falls_back_to_defaults_for_omitted_options(stored_config): ...
```

- `strict=True`: an unexpected pass fails the suite, so the marker can't outlive the fix.
- `raises=`: any other exception is reported as a real failure, not hidden.
<https://docs.pytest.org/en/stable/how-to/skipping.html#xfail-mark-test-functions-as-expected-to-fail>

## Boundaries: monkeypatch, tmp_path, the clock

- `monkeypatch.setenv`, `monkeypatch.setattr` and `monkeypatch.delenv` are undone after each test. Use them for the environment and for process-wide boundaries, not for the code under test.
  <https://docs.pytest.org/en/stable/how-to/monkeypatch.html>
- `tmp_path` gives each test its own directory on disk.
  <https://docs.pytest.org/en/stable/how-to/tmp_path.html>
- **Freeze the clock** without adding a dependency: replace the name in the module under test.

```python
FROZEN_NOW = datetime(2026, 1, 15, 23, 59, 59)

@pytest.fixture
def frozen_clock(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return FROZEN_NOW

    monkeypatch.setattr("package.module_under_test.datetime", FrozenDatetime)
```

If the repository already uses `freezegun` or `time-machine`, use that instead.

## Test classes

Classes without `__init__` and with names starting with `Test` group tests by seam.
<https://docs.pytest.org/en/stable/getting-started.html#group-multiple-tests-in-a-class>

Follow the repository's habit: if it rarely uses classes, module-level functions with a clear prefix are fine too.

## factory_boy

- **Traits** turn on a group of field values together: `SettingsFactory.build(search=True)`.
  <https://factoryboy.readthedocs.io/en/stable/reference.html#traits>
- **Mutable values:** a plain `dict` or `list` class attribute is the same object in every build. Use `factory.Dict({...})` or `factory.List([...])` for a fresh copy each time, or `factory.LazyFunction` for anything else.
  <https://factoryboy.readthedocs.io/en/stable/reference.html#dict-and-list>
- **`build()` versus `create()`:** `build()` never touches the database, so prefer it in unit tests.
