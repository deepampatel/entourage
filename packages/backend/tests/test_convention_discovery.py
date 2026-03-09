"""Tests for ConventionDiscovery service."""

from pathlib import Path

import pytest

from openclaw.services.convention_discovery import ConventionDiscovery


@pytest.fixture
def discovery():
    return ConventionDiscovery()


@pytest.fixture
def repo(tmp_path):
    """Create a temporary repo directory."""
    return tmp_path / "repo"


class TestDetectTestPatterns:
    @pytest.mark.asyncio
    async def test_detect_pytest(self, discovery, repo):
        repo.mkdir()
        pyproject = repo / "pyproject.toml"
        pyproject.write_text('[tool.pytest.ini_options]\ntestpaths = ["tests"]')

        conventions = await discovery.discover(str(repo))
        test_conv = [c for c in conventions if c["category"] == "testing"]
        assert len(test_conv) == 1
        assert test_conv[0]["name"] == "pytest"

    @pytest.mark.asyncio
    async def test_detect_pytest_with_conftest(self, discovery, repo):
        repo.mkdir()
        (repo / "pyproject.toml").write_text("[tool.pytest]")
        (repo / "conftest.py").write_text("# fixtures")

        conventions = await discovery.discover(str(repo))
        test_conv = [c for c in conventions if c["category"] == "testing"]
        assert "conftest.py present" in test_conv[0]["content"]

    @pytest.mark.asyncio
    async def test_detect_jest(self, discovery, repo):
        repo.mkdir()
        (repo / "jest.config.js").write_text("module.exports = {}")

        conventions = await discovery.discover(str(repo))
        test_conv = [c for c in conventions if c["category"] == "testing"]
        assert len(test_conv) == 1
        assert test_conv[0]["name"] == "jest"

    @pytest.mark.asyncio
    async def test_detect_vitest(self, discovery, repo):
        repo.mkdir()
        (repo / "vitest.config.ts").write_text("export default {}")

        conventions = await discovery.discover(str(repo))
        test_conv = [c for c in conventions if c["category"] == "testing"]
        assert len(test_conv) == 1
        assert test_conv[0]["name"] == "vitest"

    @pytest.mark.asyncio
    async def test_detect_cargo_test(self, discovery, repo):
        repo.mkdir()
        (repo / "Cargo.toml").write_text("[package]")

        conventions = await discovery.discover(str(repo))
        test_conv = [c for c in conventions if c["category"] == "testing"]
        assert len(test_conv) == 1
        assert test_conv[0]["name"] == "cargo-test"


class TestDetectCodeStyle:
    @pytest.mark.asyncio
    async def test_detect_eslint(self, discovery, repo):
        repo.mkdir()
        (repo / ".eslintrc.json").write_text("{}")

        conventions = await discovery.discover(str(repo))
        style_conv = [c for c in conventions if c["category"] == "code_style"]
        assert len(style_conv) == 1
        assert style_conv[0]["name"] == "eslint"

    @pytest.mark.asyncio
    async def test_detect_ruff(self, discovery, repo):
        repo.mkdir()
        (repo / "ruff.toml").write_text("[lint]")

        conventions = await discovery.discover(str(repo))
        style_conv = [c for c in conventions if c["category"] == "code_style"]
        assert len(style_conv) == 1
        assert style_conv[0]["name"] == "ruff"

    @pytest.mark.asyncio
    async def test_detect_black_in_pyproject(self, discovery, repo):
        repo.mkdir()
        (repo / "pyproject.toml").write_text("[tool.black]\nline-length = 88")

        conventions = await discovery.discover(str(repo))
        style_conv = [c for c in conventions if c["category"] == "code_style"]
        assert len(style_conv) == 1
        assert style_conv[0]["name"] == "black"

    @pytest.mark.asyncio
    async def test_detect_prettier(self, discovery, repo):
        repo.mkdir()
        (repo / ".prettierrc").write_text("{}")

        conventions = await discovery.discover(str(repo))
        style_conv = [c for c in conventions if c["category"] == "code_style"]
        assert len(style_conv) == 1
        assert style_conv[0]["name"] == "prettier"


class TestDetectBuildSystem:
    @pytest.mark.asyncio
    async def test_detect_makefile(self, discovery, repo):
        repo.mkdir()
        (repo / "Makefile").write_text("all:\n\techo hello")

        conventions = await discovery.discover(str(repo))
        build_conv = [c for c in conventions if c["category"] == "build"]
        assert len(build_conv) == 1
        assert build_conv[0]["name"] == "make"

    @pytest.mark.asyncio
    async def test_detect_npm(self, discovery, repo):
        repo.mkdir()
        (repo / "package.json").write_text("{}")

        conventions = await discovery.discover(str(repo))
        build_conv = [c for c in conventions if c["category"] == "build"]
        assert len(build_conv) == 1
        assert build_conv[0]["name"] == "npm"

    @pytest.mark.asyncio
    async def test_detect_yarn(self, discovery, repo):
        repo.mkdir()
        (repo / "package.json").write_text("{}")
        (repo / "yarn.lock").write_text("")

        conventions = await discovery.discover(str(repo))
        build_conv = [c for c in conventions if c["category"] == "build"]
        assert build_conv[0]["name"] == "yarn"

    @pytest.mark.asyncio
    async def test_detect_pnpm(self, discovery, repo):
        repo.mkdir()
        (repo / "package.json").write_text("{}")
        (repo / "pnpm-lock.yaml").write_text("")

        conventions = await discovery.discover(str(repo))
        build_conv = [c for c in conventions if c["category"] == "build"]
        assert build_conv[0]["name"] == "pnpm"


class TestDetectArchitecture:
    @pytest.mark.asyncio
    async def test_detect_monorepo(self, discovery, repo):
        repo.mkdir()
        (repo / "packages" / "backend").mkdir(parents=True)
        (repo / "packages" / "frontend").mkdir(parents=True)

        conventions = await discovery.discover(str(repo))
        arch_conv = [c for c in conventions if c["category"] == "architecture"]
        assert len(arch_conv) == 1
        assert arch_conv[0]["name"] == "monorepo"
        assert "backend" in arch_conv[0]["content"]

    @pytest.mark.asyncio
    async def test_detect_service_layer(self, discovery, repo):
        repo.mkdir()
        services_dir = repo / "src" / "myapp" / "services"
        services_dir.mkdir(parents=True)
        (services_dir / "__init__.py").write_text("")
        (services_dir / "user_service.py").write_text("class UserService: ...")
        (services_dir / "auth_service.py").write_text("class AuthService: ...")

        conventions = await discovery.discover(str(repo))
        arch_conv = [c for c in conventions if c["category"] == "architecture"]
        assert len(arch_conv) == 1
        assert arch_conv[0]["name"] == "service-layer"
        assert "user_service" in arch_conv[0]["content"]


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_nonexistent_path(self, discovery):
        conventions = await discovery.discover("/nonexistent/path")
        assert conventions == []

    @pytest.mark.asyncio
    async def test_empty_directory(self, discovery, repo):
        repo.mkdir()
        conventions = await discovery.discover(str(repo))
        assert conventions == []
