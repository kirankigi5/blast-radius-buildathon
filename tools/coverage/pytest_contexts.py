"""Explicit pytest phases and shared-fixture contexts for offline tracing."""

from contextlib import contextmanager
from collections import defaultdict

import pytest
from _pytest.fixtures import FixtureDef


class Contexts:
    def __init__(self, cov, wanted, collect_only=False):
        self.cov = cov
        self.wanted = set(wanted)
        self.collect_only = collect_only
        self.current = "shared:collection"
        self.collected = []
        self.reports = []
        self.collection_errors = []
        self.fixture_users = defaultdict(set)
        self.fixture_info = {}
        self.phases = defaultdict(set)
        self.cov.switch_context(self.current)
        # Pytest binds finish callbacks before pytest_fixture_setup is called.
        # Patch the method before collection so those bound callbacks preserve
        # the shared context too (not only direct calls to fixturedef.finish).
        self.original_finish = FixtureDef.finish

        def finish(definition, *args, **kwargs):
            key = self.fixture_key(definition)
            with self.context(f"fixture|{key}|teardown"):
                return self.original_finish(definition, *args, **kwargs)

        FixtureDef.finish = finish

    def pytest_unconfigure(self, config):
        FixtureDef.finish = self.original_finish

    @contextmanager
    def context(self, name):
        previous = self.current
        self.current = name
        self.cov.switch_context(name)
        try:
            yield
        finally:
            self.current = previous
            self.cov.switch_context(previous)

    def fixture_key(self, definition):
        key = f"{definition.baseid}::{definition.argname}::{definition.scope}"
        self.fixture_info[key] = {
            "name": definition.argname,
            "scope": definition.scope,
            "baseid": definition.baseid,
        }
        return key

    def remember_fixtures(self, item):
        # The static closure includes dependencies and all consumers of a cached
        # fixture; _fixture_defs adds dynamically requested fixtures after setup.
        for definitions in item._fixtureinfo.name2fixturedefs.values():
            for definition in definitions:
                self.fixture_users[self.fixture_key(definition)].add(item.nodeid)
        request = getattr(item, "_request", None)
        for definition in getattr(request, "_fixture_defs", {}).values():
            self.fixture_users[self.fixture_key(definition)].add(item.nodeid)

    def pytest_collection_modifyitems(self, session, config, items):
        self.collected = [
            {"id": item.nodeid, "file": str(item.path.relative_to(session.config.rootpath)),
             "location": list(item.location), "class": getattr(item.cls, "__qualname__", None),
             "parameters": getattr(getattr(item, "callspec", None), "id", None)}
            for item in items
        ]
        selected = []
        deselected = []
        for item in items:
            if item.nodeid in self.wanted:
                self.remember_fixtures(item)
                selected.append(item)
            else:
                deselected.append(item)
        items[:] = selected
        if deselected:
            config.hook.pytest_deselected(items=deselected)

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_errors.append({"id": report.nodeid, "error": str(report.longrepr)})

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        with self.context("shared:between-tests"):
            return (yield)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_setup(self, item):
        self.phases[item.nodeid].add("setup")
        with self.context(f"test|{item.nodeid}|setup"):
            try:
                return (yield)
            finally:
                self.remember_fixtures(item)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_call(self, item):
        self.phases[item.nodeid].add("call")
        with self.context(f"test|{item.nodeid}|call"):
            return (yield)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_teardown(self, item):
        self.phases[item.nodeid].add("teardown")
        with self.context(f"test|{item.nodeid}|teardown"):
            self.remember_fixtures(item)
            return (yield)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_fixture_setup(self, fixturedef, request):
        key = self.fixture_key(fixturedef)
        item = getattr(request, "_pyfuncitem", None)
        if item is not None:
            self.fixture_users[key].add(item.nodeid)
        with self.context(f"fixture|{key}|setup"):
            return (yield)

    def pytest_runtest_logreport(self, report):
        row = {"id": report.nodeid, "phase": report.when, "outcome": report.outcome,
               "report_type": type(report).__name__}
        if report.failed or report.skipped:
            row["detail"] = str(report.longrepr)
        self.reports.append(row)

    def result(self):
        return {"collected": self.collected, "reports": self.reports,
                "collection_errors": self.collection_errors,
                "fixture_users": {k: sorted(v) for k, v in sorted(self.fixture_users.items())},
                "fixtures": self.fixture_info,
                "phases": {k: sorted(v) for k, v in sorted(self.phases.items())}}
