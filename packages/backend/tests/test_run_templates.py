"""Tests for run templates in PlannerService."""

import pytest

from openclaw.services.planner_service import RUN_TEMPLATES, PlannerService


class TestRunTemplates:
    def test_feature_template_exists(self):
        assert "feature" in RUN_TEMPLATES
        assert "hints" in RUN_TEMPLATES["feature"]
        assert "budget" in RUN_TEMPLATES["feature"]

    def test_bugfix_template_exists(self):
        assert "bugfix" in RUN_TEMPLATES
        assert RUN_TEMPLATES["bugfix"]["budget"] == 5.0

    def test_refactor_template_exists(self):
        assert "refactor" in RUN_TEMPLATES

    def test_migration_template_exists(self):
        assert "migration" in RUN_TEMPLATES


class TestBuildPlanningPromptWithTemplate:
    """Test that templates inject hints into the planning prompt."""

    def _build(self, intent, template=None, conventions=None):
        """Call _build_planning_prompt without needing full service init."""
        # Call the unbound method directly to avoid DB dependency
        return PlannerService._build_planning_prompt(
            None, intent, conventions=conventions, template=template
        )

    def test_feature_hints_in_prompt(self):
        prompt = self._build("Add user auth", template="feature")
        assert "Run template: feature" in prompt
        assert "DB migration" in prompt
        assert "Add user auth" in prompt

    def test_bugfix_hints_in_prompt(self):
        prompt = self._build("Fix login bug", template="bugfix")
        assert "Run template: bugfix" in prompt
        assert "failing test" in prompt

    def test_refactor_hints_in_prompt(self):
        prompt = self._build("Refactor auth module", template="refactor")
        assert "Keep behavior unchanged" in prompt

    def test_no_template_works(self):
        prompt = self._build("Do something")
        assert "Run template:" not in prompt
        assert "Do something" in prompt

    def test_unknown_template_ignored(self):
        prompt = self._build("Build spaceship", template="nonexistent")
        assert "Run template:" not in prompt
        assert "Build spaceship" in prompt

    def test_template_with_conventions(self):
        conventions = [{"name": "pytest", "content": "Use pytest fixtures"}]
        prompt = self._build(
            "Add feature", template="feature", conventions=conventions
        )
        assert "Run template: feature" in prompt
        assert "pytest" in prompt
        assert "Use pytest fixtures" in prompt
