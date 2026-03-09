"""Convention discovery — scan a repo for patterns and conventions.

Before planning a pipeline, we scan the target repository to discover
existing conventions: test frameworks, code style tools, build systems,
and architectural patterns. These are injected into the planning prompt
so the LLM generates tasks that follow the repo's existing patterns.

Learn: Pattern detection is file-based (check for config files, directory
structure) rather than AST-based. This makes it fast and language-agnostic.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openclaw.services.convention_discovery")


class ConventionDiscovery:
    """Scan a repository for development conventions and patterns."""

    async def discover(self, repo_path: str) -> list[dict]:
        """Scan repo for patterns. Returns list of convention dicts.

        Each dict has: {name: str, content: str, category: str}
        """
        path = Path(repo_path)
        if not path.exists():
            logger.warning("Repo path %s does not exist", repo_path)
            return []

        conventions: list[dict] = []

        detectors = [
            self._detect_test_patterns,
            self._detect_code_style,
            self._detect_build_system,
            self._detect_architecture,
        ]

        for detector in detectors:
            result = await detector(path)
            if result:
                conventions.append(result)

        logger.info(
            "Discovered %d conventions in %s", len(conventions), repo_path
        )
        return conventions

    async def _detect_test_patterns(self, repo_path: Path) -> Optional[dict]:
        """Detect test framework: pytest, jest, vitest, cargo test, go test."""

        # Python: pytest
        if (repo_path / "pytest.ini").exists() or (
            repo_path / "pyproject.toml"
        ).exists():
            pyproject = repo_path / "pyproject.toml"
            if pyproject.exists():
                content = pyproject.read_text()
                if "pytest" in content or "[tool.pytest" in content:
                    conftest = repo_path / "conftest.py"
                    hints = "pytest detected via pyproject.toml"
                    if conftest.exists():
                        hints += "; conftest.py present"
                    return {
                        "name": "pytest",
                        "content": hints,
                        "category": "testing",
                    }

        # JavaScript: jest
        if (repo_path / "jest.config.js").exists() or (
            repo_path / "jest.config.ts"
        ).exists():
            return {
                "name": "jest",
                "content": "Jest test framework detected",
                "category": "testing",
            }

        # JavaScript: vitest
        if (repo_path / "vitest.config.ts").exists() or (
            repo_path / "vitest.config.js"
        ).exists():
            return {
                "name": "vitest",
                "content": "Vitest test framework detected",
                "category": "testing",
            }

        # Rust: cargo test
        if (repo_path / "Cargo.toml").exists():
            return {
                "name": "cargo-test",
                "content": "Rust project with cargo test",
                "category": "testing",
            }

        # Go: go test
        if (repo_path / "go.mod").exists():
            return {
                "name": "go-test",
                "content": "Go project with go test",
                "category": "testing",
            }

        return None

    async def _detect_code_style(self, repo_path: Path) -> Optional[dict]:
        """Detect code style tools: eslint, prettier, black, ruff."""

        # Python: ruff
        if (repo_path / "ruff.toml").exists():
            return {
                "name": "ruff",
                "content": "Ruff linter/formatter detected via ruff.toml",
                "category": "code_style",
            }

        # Python: ruff in pyproject.toml
        pyproject = repo_path / "pyproject.toml"
        if pyproject.exists():
            content = pyproject.read_text()
            if "[tool.ruff" in content:
                return {
                    "name": "ruff",
                    "content": "Ruff linter/formatter detected via pyproject.toml",
                    "category": "code_style",
                }
            if "[tool.black" in content:
                return {
                    "name": "black",
                    "content": "Black formatter detected via pyproject.toml",
                    "category": "code_style",
                }

        # JavaScript: eslint
        eslint_files = [
            ".eslintrc.js",
            ".eslintrc.cjs",
            ".eslintrc.json",
            "eslint.config.js",
            "eslint.config.mjs",
        ]
        for f in eslint_files:
            if (repo_path / f).exists():
                return {
                    "name": "eslint",
                    "content": f"ESLint detected via {f}",
                    "category": "code_style",
                }

        # Prettier
        prettier_files = [
            ".prettierrc",
            ".prettierrc.json",
            ".prettierrc.js",
            "prettier.config.js",
        ]
        for f in prettier_files:
            if (repo_path / f).exists():
                return {
                    "name": "prettier",
                    "content": f"Prettier detected via {f}",
                    "category": "code_style",
                }

        return None

    async def _detect_build_system(self, repo_path: Path) -> Optional[dict]:
        """Detect build system: make, npm, cargo, gradle, maven."""

        # Makefile
        if (repo_path / "Makefile").exists():
            return {
                "name": "make",
                "content": "Makefile-based build system detected",
                "category": "build",
            }

        # npm/yarn/pnpm
        if (repo_path / "package.json").exists():
            lock = "npm"
            if (repo_path / "yarn.lock").exists():
                lock = "yarn"
            elif (repo_path / "pnpm-lock.yaml").exists():
                lock = "pnpm"
            elif (repo_path / "bun.lockb").exists():
                lock = "bun"
            return {
                "name": lock,
                "content": f"Node.js project using {lock}",
                "category": "build",
            }

        # Cargo (Rust)
        if (repo_path / "Cargo.toml").exists():
            return {
                "name": "cargo",
                "content": "Rust project using Cargo",
                "category": "build",
            }

        # Gradle
        if (repo_path / "build.gradle").exists() or (
            repo_path / "build.gradle.kts"
        ).exists():
            return {
                "name": "gradle",
                "content": "Gradle build system detected",
                "category": "build",
            }

        # Maven
        if (repo_path / "pom.xml").exists():
            return {
                "name": "maven",
                "content": "Maven build system detected",
                "category": "build",
            }

        return None

    async def _detect_architecture(self, repo_path: Path) -> Optional[dict]:
        """Detect architectural patterns: service layers, DI, monorepo."""

        # Monorepo with packages
        packages_dir = repo_path / "packages"
        if packages_dir.is_dir():
            subs = [d.name for d in packages_dir.iterdir() if d.is_dir()]
            return {
                "name": "monorepo",
                "content": f"Monorepo with packages: {', '.join(subs[:5])}",
                "category": "architecture",
            }

        # Python service layer
        src_dir = repo_path / "src"
        services_dir = None
        if src_dir.is_dir():
            for d in src_dir.rglob("services"):
                if d.is_dir():
                    services_dir = d
                    break

        if services_dir:
            service_files = [
                f.stem for f in services_dir.glob("*.py") if f.stem != "__init__"
            ]
            return {
                "name": "service-layer",
                "content": (
                    f"Service layer pattern: {', '.join(service_files[:5])}"
                ),
                "category": "architecture",
            }

        return None
