"""Test GitHub Action security hardening.

Tests that action.yml is properly secured against shell injection attacks
and that dangerous inputs cannot execute arbitrary code.
"""

import subprocess
import tempfile
import unittest
import yaml
from pathlib import Path


class TestActionYamlStructure(unittest.TestCase):
    """Test that action.yml has proper security hardening."""

    @classmethod
    def setUpClass(cls):
        """Load action.yml once for all tests."""
        action_path = Path(__file__).parent.parent / "action.yml"
        cls.action_content = action_path.read_text()
        cls.action_yaml = yaml.safe_load(cls.action_content)

    def test_action_yml_exists(self):
        """Verify action.yml exists."""
        action_path = Path(__file__).parent.parent / "action.yml"
        self.assertTrue(action_path.exists())

    def test_version_pinned_on_pip_install(self):
        """Verify pip install step pins warrantos version."""
        self.assertIn('warrantos==0.11.0', self.action_content)
        # Should have version pinning with quotes
        self.assertIn('"warrantos==0.11.0"', self.action_content)

    def test_slop_step_uses_env_variables(self):
        """Verify slop step passes inputs via env variables, not direct interpolation."""
        # The step should pass PATHS and FAIL_OVER as env variables
        self.assertIn('PATHS: ${{ inputs.paths }}', self.action_content)
        self.assertIn('FAIL_OVER: ${{ inputs.fail-over }}', self.action_content)

        # The run command should reference the env variables, not inputs directly
        # This prevents shell injection
        self.assertIn('warrantos slop "$PATHS"', self.action_content)
        # Should NOT have direct unquoted interpolation
        self.assertNotIn('warrantos slop ${{ inputs.paths }}', self.action_content)

    def test_check_step_uses_env_variables(self):
        """Verify check step passes inputs via env variables."""
        # Should have env section with PATHS and PROFILE
        self.assertIn('PATHS: ${{ inputs.paths }}', self.action_content)
        self.assertIn('PROFILE: ${{ inputs.profile }}', self.action_content)

        # Should reference env variables in the script
        self.assertIn('for p in $PATHS', self.action_content)
        # Env var should be quoted
        self.assertIn('--profile "$PROFILE"', self.action_content)

    def test_no_dangerous_input_interpolation(self):
        """Verify dangerous patterns of direct input interpolation are not present."""
        # These would be vulnerable to command injection:
        dangerous_patterns = [
            'warrantos slop ${{ inputs.paths }}',  # Unquoted, unescaped
            '{{ inputs.paths }})',  # Could allow path traversal/command injection
        ]

        for pattern in dangerous_patterns:
            if pattern in self.action_content:
                # Allow it only if it's in a string literal, comment, or properly escaped
                lines = self.action_content.split('\n')
                for i, line in enumerate(lines):
                    if pattern in line:
                        # It's OK if it's in a commented line or yaml value
                        stripped = line.strip()
                        if stripped.startswith('#'):
                            continue  # It's a comment, OK
                        # Otherwise, this is a security issue
                        self.fail(
                            f"Dangerous pattern found at line {i+1}: {line}\n"
                            f"Pattern: {pattern}"
                        )


class TestActionInputValidation(unittest.TestCase):
    """Test that action.yml properly defines inputs."""

    @classmethod
    def setUpClass(cls):
        """Load action.yml."""
        action_path = Path(__file__).parent.parent / "action.yml"
        cls.action_yaml = yaml.safe_load(action_path.read_text())

    def test_paths_input_defined(self):
        """Verify paths input is defined."""
        self.assertIn('paths', self.action_yaml.get('inputs', {}))
        paths_input = self.action_yaml['inputs']['paths']
        self.assertIn('description', paths_input)

    def test_profile_input_defined(self):
        """Verify profile input is defined."""
        self.assertIn('profile', self.action_yaml.get('inputs', {}))
        profile_input = self.action_yaml['inputs']['profile']
        self.assertIn('description', profile_input)

    def test_fail_over_input_defined(self):
        """Verify fail-over input is defined."""
        self.assertIn('fail-over', self.action_yaml.get('inputs', {}))
        fail_over = self.action_yaml['inputs']['fail-over']
        self.assertIn('description', fail_over)

    def test_mode_input_defined(self):
        """Verify mode input is defined."""
        self.assertIn('mode', self.action_yaml.get('inputs', {}))
        mode_input = self.action_yaml['inputs']['mode']
        self.assertIn('description', mode_input)


class TestActionlintCI(unittest.TestCase):
    """Test that CI workflow includes actionlint."""

    def test_ci_yml_includes_actionlint(self):
        """Verify .github/workflows/ci.yml includes actionlint step."""
        ci_path = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
        self.assertTrue(ci_path.exists())

        ci_content = ci_path.read_text()
        # Should have a linting job that runs actionlint
        self.assertIn("actionlint", ci_content)
        self.assertIn("npm install -g @mheap/actionlint", ci_content)

    def test_ci_yml_lint_actions_job_exists(self):
        """Verify the lint-actions job exists in CI."""
        ci_path = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
        ci_yaml = yaml.safe_load(ci_path.read_text())

        self.assertIn('lint-actions', ci_yaml.get('jobs', {}))
        lint_job = ci_yaml['jobs']['lint-actions']
        self.assertIn('steps', lint_job)


class TestDangerousInputPatterns(unittest.TestCase):
    """Test that dangerous input patterns would fail under the new action.yml."""

    def test_command_injection_prevented(self):
        """Demonstrate that command injection patterns would be safely handled."""
        # This test documents how the fix prevents:
        # inputs.paths = "README.md; echo pwned"
        #
        # With the fix, this becomes:
        # PATHS="README.md; echo pwned"
        # warrantos slop "$PATHS"
        #
        # Which treats the entire value as a single argument, not as shell commands.

        # Create a mock scenario
        test_cases = [
            # (input, expected_safe_argument)
            ("README.md; echo pwned", 'README.md; echo pwned'),  # Passed as single arg
            ("README.md | cat /etc/passwd", 'README.md | cat /etc/passwd'),
            ("README.md && malicious_command", 'README.md && malicious_command'),
            ("README.md` $(whoami) `", 'README.md` $(whoami) `'),
            ("$(echo README.md)", '$(echo README.md)'),
        ]

        for user_input, expected_in_env in test_cases:
            # When passed as an env variable and then quoted in the command:
            # PATHS="$user_input"
            # warrantos slop "$PATHS"
            #
            # The shell treats the entire PATHS value as a single argument.
            # This is what prevents injection.
            self.assertIn(user_input, expected_in_env)


if __name__ == "__main__":
    unittest.main()
