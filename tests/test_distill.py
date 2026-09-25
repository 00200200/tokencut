from __future__ import annotations

from usagetrim.core.cache import ContextCache
from usagetrim.core.distill import distill_conversation


def test_distill_conversation_markdown_dialogue():
    transcript = (
        "User: Can we fix the bug in src/api/client.py?\n\n"
        "Assistant: Sure, I see the bug. We decided to implement retry logic with exponential backoff.\n\n"
        "User: Sounds good, but make sure not to use external libraries.\n\n"
        "Assistant: Understood. We chose to use standard library urllib instead. "
        "The previous request failed because of connection timeout.\n"
        "Updated src/api/client.py and verified tests pass.\n"
    )
    res = distill_conversation(transcript, budget=1000)
    assert res.message_count >= 4
    assert "src/api/client.py" in res.files_referenced
    assert "Distilled Conversation Context" in res.text
    assert "Goals & User Inquiries" in res.text
    assert "retry logic" in res.text or "urllib" in res.text
    assert res.ref_id is not None
    # Verify CCR retrieval of full original
    recovered = ContextCache().retrieve(res.ref_id)
    assert "exponential backoff" in recovered


def test_distill_conversation_json_lines():
    import json

    lines = [
        json.dumps({"role": "user", "content": "Let's optimize database queries in db/session.py"}),
        json.dumps({"role": "assistant", "content": "I agree on adding an index to users.id."}),
    ]
    raw = "\n".join(lines)
    res = distill_conversation(raw, budget=1000)
    assert res.message_count == 2
    assert "db/session.py" in res.files_referenced


def test_distill_conversation_thought_block_pruning():
    raw = (
        "User: Start migration.\n\n"
        "Assistant: <thinking>Let me think through the migration steps...</thinking>\n"
        "We configured the database schema in models/user.py.\n"
    )
    res = distill_conversation(raw, budget=1000)
    assert "<thinking>" not in res.text
    assert "Let me think" not in res.text
    assert "models/user.py" in res.files_referenced


def test_distill_conversation_budget_enforcement():
    # Long conversation with many turns
    dialogue = []
    for i in range(50):
        dialogue.append(f"User: Step {i} for src/module_{i}.py")
        dialogue.append(f"Assistant: We decided to implement feature {i}. Everything is working.")
    raw = "\n\n".join(dialogue)

    res = distill_conversation(raw, budget=200)
    assert res.distilled_tokens <= 250
    assert "Full transcript reference" in res.text or "truncated to fit" in res.text
