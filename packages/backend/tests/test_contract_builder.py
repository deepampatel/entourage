"""Tests for ContractBuilder — contract generation and management."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.services.contract_builder import ContractBuilder


# ═══════════════════════════════════════════════════════════
# Unit tests (no DB needed)
# ═══════════════════════════════════════════════════════════


class TestShouldGenerateContracts:
    """Test boundary detection logic."""

    def test_single_task_no_contracts(self):
        tasks = [{"title": "Do stuff", "integration_hints": ["user_api"]}]
        assert ContractBuilder._should_generate_contracts(tasks) is False

    def test_no_shared_hints(self):
        tasks = [
            {"title": "Task A", "integration_hints": ["auth"]},
            {"title": "Task B", "integration_hints": ["payments"]},
        ]
        assert ContractBuilder._should_generate_contracts(tasks) is False

    def test_shared_hints_triggers_contracts(self):
        tasks = [
            {"title": "Task A", "integration_hints": ["user_api", "db_schema"]},
            {"title": "Task B", "integration_hints": ["user_api"]},
        ]
        assert ContractBuilder._should_generate_contracts(tasks) is True

    def test_empty_hints_no_contracts(self):
        tasks = [
            {"title": "Task A", "integration_hints": []},
            {"title": "Task B", "integration_hints": []},
        ]
        assert ContractBuilder._should_generate_contracts(tasks) is False

    def test_multiple_shared_hints(self):
        tasks = [
            {"title": "Task A", "integration_hints": ["user_api", "event_bus"]},
            {"title": "Task B", "integration_hints": ["user_api", "event_bus"]},
            {"title": "Task C", "integration_hints": ["event_bus"]},
        ]
        assert ContractBuilder._should_generate_contracts(tasks) is True

    def test_missing_hints_key(self):
        tasks = [
            {"title": "Task A"},
            {"title": "Task B"},
        ]
        assert ContractBuilder._should_generate_contracts(tasks) is False


class TestExtractContracts:
    """Test contract extraction from Claude response."""

    def test_extracts_contracts_from_tool_use(self):
        contracts_data = [
            {
                "contract_type": "api",
                "name": "UserService.get_by_email",
                "producer_task_index": 0,
                "specification": {
                    "function_name": "get_by_email",
                    "parameters": [{"name": "email", "type": "str"}],
                    "return_type": "User",
                },
            }
        ]
        block = MagicMock()
        block.type = "tool_use"
        block.name = "create_contracts"
        block.input = {"contracts": contracts_data}

        response = MagicMock()
        response.content = [block]

        result = ContractBuilder._extract_contracts(response)
        assert len(result) == 1
        assert result[0]["name"] == "UserService.get_by_email"

    def test_no_tool_use_returns_empty(self):
        block = MagicMock()
        block.type = "text"
        block.text = "No contracts needed."

        response = MagicMock()
        response.content = [block]

        result = ContractBuilder._extract_contracts(response)
        assert result == []

    def test_wrong_tool_name_returns_empty(self):
        block = MagicMock()
        block.type = "tool_use"
        block.name = "wrong_tool"
        block.input = {"contracts": [{"name": "test"}]}

        response = MagicMock()
        response.content = [block]

        result = ContractBuilder._extract_contracts(response)
        assert result == []


class TestBuildContractPrompt:
    """Test prompt construction."""

    def test_includes_all_tasks(self):
        builder = ContractBuilder.__new__(ContractBuilder)
        tasks = [
            {
                "title": "Add user model",
                "description": "Create User SQLAlchemy model",
                "assigned_role": "engineer",
                "dependencies": [],
                "integration_hints": ["user_api"],
            },
            {
                "title": "Add user API",
                "description": "Create /users REST endpoints",
                "assigned_role": "engineer",
                "dependencies": [0],
                "integration_hints": ["user_api"],
            },
        ]
        prompt = builder._build_contract_prompt(tasks)
        assert "Task 0: Add user model" in prompt
        assert "Task 1: Add user API" in prompt
        assert "user_api" in prompt
        assert "**Depends on:** Tasks [0]" in prompt

    def test_handles_minimal_task(self):
        builder = ContractBuilder.__new__(ContractBuilder)
        tasks = [{"title": "Simple task"}]
        prompt = builder._build_contract_prompt(tasks)
        assert "Task 0: Simple task" in prompt


# ═══════════════════════════════════════════════════════════
# Integration tests (need PostgreSQL)
# ═══════════════════════════════════════════════════════════


def _mock_claude_contract_response():
    """Build a mock Anthropic response with contract tool call."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "create_contracts"
    block.input = {
        "contracts": [
            {
                "contract_type": "api",
                "name": "UserService.get_by_email",
                "producer_task_index": 0,
                "consumer_task_indices": [1],
                "specification": {
                    "function_name": "get_by_email",
                    "parameters": [{"name": "email", "type": "str"}],
                    "return_type": "User",
                    "module_path": "services/user_service.py",
                },
            },
            {
                "contract_type": "type",
                "name": "User",
                "producer_task_index": 0,
                "consumer_task_indices": [1],
                "specification": {
                    "type_name": "User",
                    "fields": [
                        {"name": "id", "type": "uuid", "optional": False},
                        {"name": "email", "type": "str", "optional": False},
                        {"name": "name", "type": "str", "optional": True},
                    ],
                    "module_path": "models/user.py",
                },
            },
        ]
    }
    response = MagicMock()
    response.content = [block]
    return response
