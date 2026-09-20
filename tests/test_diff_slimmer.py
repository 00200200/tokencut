from tokencut.core.diff_slimmer import slim_git_diff

SAMPLE_DIFF = """diff --git a/src/main.py b/src/main.py
index 1234567..89abcdef 100644
--- a/src/main.py
+++ b/src/main.py
@@ -10,6 +10,7 @@ def process():
     context_line_1
     context_line_2
     context_line_3
+    new_important_logic()
     context_line_4
     context_line_5
diff --git a/uv.lock b/uv.lock
index aaaaaaa..bbbbbbb 100644
--- a/uv.lock
+++ b/uv.lock
@@ -1,500 +1,500 @@
-old_package_version = "1.0.0"
+new_package_version = "1.0.1"
""" + "\n".join([f"+ extra_lock_line_{i}" for i in range(100)])


def test_slim_git_diff_folds_lockfile():
    slimmed = slim_git_diff(SAMPLE_DIFF)
    assert "diff --git a/src/main.py b/src/main.py" in slimmed
    assert "+    new_important_logic()" in slimmed
    # Lockfile lines should be folded
    assert "diff --git a/uv.lock b/uv.lock" in slimmed
    assert "lines of lockfile/generated diff omitted by tokencut" in slimmed
    assert "+ extra_lock_line_50" not in slimmed
