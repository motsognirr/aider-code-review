"""Every key run_review.sh writes to $GITHUB_OUTPUT must be an action output.

A composite action only exposes outputs declared in action.yml; anything else
written to the step's GITHUB_OUTPUT is silently invisible to callers.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def written_keys():
    text = (REPO_ROOT / "scripts" / "run_review.sh").read_text()
    return set(re.findall(r'echo "([a-z_]+)=', text))


def declared_outputs():
    text = (REPO_ROOT / "action.yml").read_text()
    block = re.search(r"^outputs:\n(.*?)^\S", text, re.DOTALL | re.MULTILINE).group(1)
    return set(re.findall(r"^  ([a-z_]+):$", block, re.MULTILINE))


def test_every_written_output_is_declared():
    assert written_keys() - declared_outputs() == set()


def test_written_keys_are_found():
    # Guard the regexes: if parsing silently finds nothing, the test above is vacuous.
    assert {"findings_count", "skipped"} <= written_keys()
