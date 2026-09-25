import json
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from usagetrim.cli import app
from usagetrim.core.doctor import (
    configure_codex_mcp,
)
from usagetrim.core.prepare import prepare_text
from usagetrim.core.rules_linter import generate_desktop_rules
from usagetrim.core.specialized import (
    auto_specialize_command_output,
    filter_dev_server_logs,
    filter_traceback,
)
from usagetrim.mcp import server
from usagetrim.metrics.tokenizer import count_tokens


def test_desktop_mcp_profile_tools_and_schema_reduction():
    full_tools = server.tool_definitions("full")
    desktop_tools = server.tool_definitions("desktop")

    # Desktop profile must expose exactly the DESKTOP_TOOLS set
    tool_names = {t["name"] for t in desktop_tools}
    assert tool_names == server.DESKTOP_TOOLS
    assert "usagetrim_code" in tool_names
    assert "usagetrim_read" in tool_names
    assert "usagetrim_edit_symbol" in tool_names
    assert "usagetrim_exec" in tool_names
    assert "usagetrim_optimize" in tool_names
    assert "usagetrim_clip" in tool_names
    assert "usagetrim_retrieve" in tool_names
    assert "usagetrim_gain" in tool_names

    # Schema descriptions should be minimized for desktop context
    full_tokens = count_tokens(json.dumps(full_tools)).openai
    desktop_tokens = count_tokens(json.dumps(desktop_tools)).openai
    assert desktop_tokens < full_tokens * 0.70  # at least 30% reduction vs full

    # Instructions contain Desktop label
    instructions = server.server_instructions("desktop")
    assert "Desktop Profile" in instructions


def test_configure_codex_mcp_new_file(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        "usagetrim.core.doctor.shutil.which", lambda _: str(tmp_path / "bin" / "usagetrim")
    )

    target_cfg = tmp_path / ".codex" / "config.toml"
    ok, path_str = configure_codex_mcp(target_file=target_cfg, profile="desktop")
    assert ok is True
    assert Path(path_str) == target_cfg
    assert target_cfg.exists()

    content = target_cfg.read_text(encoding="utf-8")
    parsed = tomllib.loads(content)
    assert "mcp_servers" in parsed
    assert "usagetrim" in parsed["mcp_servers"]
    usagetrim_cfg = parsed["mcp_servers"]["usagetrim"]
    assert usagetrim_cfg["command"] == str(tmp_path / "bin" / "usagetrim")
    assert usagetrim_cfg["args"] == ["mcp", "--profile", "desktop"]


def test_configure_codex_mcp_preserves_existing_tables_and_comments(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "usagetrim.core.doctor.shutil.which", lambda _: str(tmp_path / "bin" / "usagetrim")
    )

    target_cfg = tmp_path / "config.toml"
    initial_toml = (
        "# Top-level comment\n"
        'model = "gpt-4o"\n\n'
        "[mcp_servers.other]\n"
        'command = "other-tool"\n'
        'args = ["serve"]\n\n'
        "[mcp_servers.usagetrim]\n"
        'command = "old-path"\n'
        'args = ["mcp", "--profile", "coding"]\n\n'
        "[mcp_servers.usagetrim.env]\n"
        'CUSTOM_KEY = "custom_val"\n'
    )
    target_cfg.write_text(initial_toml, encoding="utf-8")

    ok, path_str = configure_codex_mcp(target_file=target_cfg, profile="desktop")
    assert ok is True

    updated_content = target_cfg.read_text(encoding="utf-8")
    assert 'model = "gpt-4o"' in updated_content
    assert "[mcp_servers.other]" in updated_content

    parsed = tomllib.loads(updated_content)
    assert parsed["model"] == "gpt-4o"
    assert parsed["mcp_servers"]["other"]["command"] == "other-tool"
    assert parsed["mcp_servers"]["usagetrim"]["command"] == str(tmp_path / "bin" / "usagetrim")
    assert parsed["mcp_servers"]["usagetrim"]["args"] == ["mcp", "--profile", "desktop"]
    # Existing env table should be preserved
    assert parsed["mcp_servers"]["usagetrim"]["env"]["CUSTOM_KEY"] == "custom_val"

    # Verify backup was created
    backups = list(tmp_path.glob("*.pre-usagetrim-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == initial_toml

    # Idempotent call should not create second backup
    ok2, _ = configure_codex_mcp(target_file=target_cfg, profile="desktop")
    assert ok2 is True
    assert len(list(tmp_path.glob("*.pre-usagetrim-*"))) == 1


def test_filter_python_traceback_collapses_library_frames():
    raw_tb = (
        "Traceback (most recent call last):\n"
        '  File "/Users/alice/projects/myapp/main.py", line 45, in run\n'
        "    result = process_data(payload)\n"
        '  File "/Users/alice/projects/myapp/services/processor.py", line 12, in process_data\n'
        "    return validate_model(payload)\n"
        '  File "/Users/alice/.venv/lib/python3.11/site-packages/pydantic/main.py", line 341, in validate_model\n'
        "    values, fields_set, validation_error = validate_model(\n"
        '  File "/Users/alice/.venv/lib/python3.11/site-packages/pydantic/fields.py", line 110, in validate\n'
        "    v, errors = self._validate_sequence_like(v, values, loc, cls)\n"
        '  File "/Users/alice/.venv/lib/python3.11/site-packages/pydantic/validators.py", line 285, in dict_validator\n'
        '    raise ValidationError("not a valid dict")\n'
        '  File "/Users/alice/.venv/lib/python3.11/site-packages/pydantic/errors.py", line 12, in error\n'
        "    return str(val)\n"
        "pydantic.error_wrappers.ValidationError: 1 validation error for Model\n"
    )

    filtered = filter_traceback(raw_tb)
    assert "main.py" in filtered
    assert "processor.py" in filtered
    assert "pydantic/errors.py" in filtered
    assert "library frames in site-packages/ omitted" in filtered
    assert "ValidationError: 1 validation error for Model" in filtered

    # Verify token reduction
    before_tokens = count_tokens(raw_tb).openai
    after_tokens = count_tokens(filtered).openai
    assert after_tokens < before_tokens


def test_filter_node_traceback_collapses_internal_frames():
    raw_node_tb = (
        "TypeError: Cannot read properties of undefined (reading 'map')\n"
        "    at renderItems (/Users/alice/projects/web/src/components/List.tsx:28:14)\n"
        "    at Object.render (/Users/alice/projects/web/src/App.tsx:15:9)\n"
        "    at node_modules/react-dom/cjs/react-dom.development.js:1234:20\n"
        "    at mountIndeterminateComponent (node_modules/react-dom/cjs/react-dom.development.js:20103:13)\n"
        "    at beginWork (node_modules/react-dom/cjs/react-dom.development.js:21601:16)\n"
        "    at HTMLUnknownElement.callCallback (node_modules/react-dom/cjs/react-dom.development.js:4164:14)\n"
        "    at processTicksAndRejections (node:internal/process/task_queues:95:5)\n"
    )

    filtered = filter_traceback(raw_node_tb)
    assert "List.tsx" in filtered
    assert "App.tsx" in filtered
    assert "internal/node_modules frames omitted" in filtered
    assert "TypeError: Cannot read properties of undefined" in filtered


def test_filter_dev_server_logs():
    raw_logs = (
        "[vite] page reload src/App.tsx\n"
        "[vite] hmr update /src/index.css\n"
        "[vite] hmr update /src/components/Header.tsx\n"
        "[vite] hmr update /src/components/Footer.tsx\n"
        "[vite] hmr update /src/components/Sidebar.tsx\n"
        "GET /api/user 200 OK - 12ms\n"
        "GET /api/user 200 OK - 8ms\n"
        "GET /api/user 200 OK - 10ms\n"
        "GET /api/user 200 OK - 7ms\n"
        "GET /api/user 200 OK - 9ms\n"
        "GET /_next/static/chunks/main.js 200 in 2ms\n"
        "GET /_next/static/chunks/app.js 304 in 1ms\n"
        "GET /_next/static/chunks/style.css 200 in 3ms\n"
        "POST /api/action 500 Internal Server Error in 45ms\n"
    )

    filtered = filter_dev_server_logs(raw_logs)
    assert "page reload src/App.tsx" in filtered
    assert "Vite HMR updates collapsed" in filtered
    assert "repeated 5x" in filtered
    assert "static asset requests (200/304 OK) collapsed" in filtered
    # Error line must be preserved
    assert "500 Internal Server Error" in filtered


def test_auto_specialize_routes_dev_server_and_traceback():
    tb_cmd_out = auto_specialize_command_output(
        "python main.py",
        "Traceback (most recent call last):\n"
        '  File "app.py", line 1, in <module>\n'
        '  File "site-packages/a.py", line 2, in f1\n'
        '  File "site-packages/b.py", line 3, in f2\n'
        '  File "site-packages/c.py", line 4, in f3\n'
        "ValueError: bad value",
    )
    assert tb_cmd_out is not None
    assert "site-packages/ omitted" in tb_cmd_out

    dev_cmd_out = auto_specialize_command_output(
        "npm run dev",
        "[vite] hmr update /a.js\n[vite] hmr update /b.js\n[vite] hmr update /c.js\n",
    )
    assert dev_cmd_out is not None
    assert "HMR updates collapsed" in dev_cmd_out


def test_prepare_text_desktop_mode():
    sample = (
        "Traceback (most recent call last):\n"
        '  File "/Users/alice/myapp/app.py", line 10, in run\n'
        '  File "/Users/alice/.venv/lib/python3.11/site-packages/pkg/a.py", line 1, in a\n'
        '  File "/Users/alice/.venv/lib/python3.11/site-packages/pkg/b.py", line 2, in b\n'
        '  File "/Users/alice/.venv/lib/python3.11/site-packages/pkg/c.py", line 3, in c\n'
        "ZeroDivisionError: division by zero\n"
    )

    res = prepare_text(sample, mode="desktop")
    assert res["mode"] == "desktop"
    assert "site-packages/" in res["text"]
    assert "ZeroDivisionError" in res["text"]


def test_generate_desktop_rules():
    claude_rules = generate_desktop_rules("claude")
    assert "UsageTrim Claude Rules" in claude_rules
    assert "usagetrim_code" in claude_rules
    assert "usagetrim_read" in claude_rules
    assert "usagetrim_edit_symbol" in claude_rules

    codex_rules = generate_desktop_rules("codex")
    assert "UsageTrim Codex Rules" in codex_rules
    assert "usagetrim_code" in codex_rules
    assert "usagetrim_read" in codex_rules


def test_cli_rules_command(tmp_path):
    runner = CliRunner()
    target_claude = tmp_path / "CLAUDE.md"
    res = runner.invoke(
        app, ["rules", "--init", "--client", "claude", "--file", str(target_claude)]
    )
    assert res.exit_code == 0
    assert target_claude.exists()
    assert "UsageTrim Claude Rules" in target_claude.read_text(encoding="utf-8")

    target_codex = tmp_path / "AGENTS.md"
    res_codex = runner.invoke(
        app, ["rules", "--init", "--client", "codex", "--file", str(target_codex)]
    )
    assert res_codex.exit_code == 0
    assert target_codex.exists()
    assert "UsageTrim Codex Rules" in target_codex.read_text(encoding="utf-8")


def test_cli_install_codex(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        "usagetrim.core.doctor.shutil.which", lambda _: str(tmp_path / "bin" / "usagetrim")
    )

    runner = CliRunner()
    res = runner.invoke(app, ["install", "--codex"])
    assert res.exit_code == 0
    codex_file = tmp_path / ".codex" / "config.toml"
    assert codex_file.exists()
    assert "[mcp_servers.usagetrim]" in codex_file.read_text()
