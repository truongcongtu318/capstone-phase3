import unittest
from pathlib import Path


WORKFLOW = Path(".github/workflows/terraform-apply.yml")
WORKFLOW_TEXT = WORKFLOW.read_text(encoding="utf-8")


class Pm127TerraformRolloutContractTests(unittest.TestCase):
    def test_scope_is_a_closed_choice_with_full_as_default(self):
        self.assertIn("      scope:\n", WORKFLOW_TEXT)
        self.assertIn("        default: full\n", WORKFLOW_TEXT)
        self.assertIn("          - full\n", WORKFLOW_TEXT)
        self.assertIn("          - pm127-kyverno-ecr\n", WORKFLOW_TEXT)
        self.assertIn(
            "      scope:\n"
            "        description: Limit the saved plan to an approved rollout scope\n"
            "        required: true\n"
            "        type: choice\n",
            WORKFLOW_TEXT,
        )

    @staticmethod
    def _scope_block(scope_name):
        """Return the shell `case` branch for one rollout scope.

        Counting `-target=` across the whole file breaks the moment a second
        scoped rollout is added, so each scope asserts against its own branch
        (from the `<scope>)` label up to the terminating `;;`).
        """
        start = WORKFLOW_TEXT.index(f"{scope_name})")
        end = WORKFLOW_TEXT.index(";;", start)
        return WORKFLOW_TEXT[start:end]

    def test_pm127_scope_targets_only_role_and_inline_policy(self):
        pm127_block = self._scope_block("pm127-kyverno-ecr")
        self.assertEqual(pm127_block.count("-target="), 2)
        self.assertIn("-target=aws_iam_role.kyverno_ecr", pm127_block)
        self.assertIn(
            "-target=aws_iam_role_policy.kyverno_ecr_read", pm127_block
        )
        self.assertIn('case "$PLAN_SCOPE" in', WORKFLOW_TEXT)
        self.assertIn("Unsupported Terraform rollout scope", WORKFLOW_TEXT)

    def test_pm18_scope_targets_only_network_module(self):
        pm18_block = self._scope_block("pm18-a1-vpc-endpoints")
        self.assertEqual(pm18_block.count("-target="), 1)
        self.assertIn("-target=module.network", pm18_block)
        self.assertIn("          - pm18-a1-vpc-endpoints\n", WORKFLOW_TEXT)

    def test_apply_consumes_only_the_hashed_saved_plan(self):
        self.assertIn("sha256sum tfplan > tfplan.sha256", WORKFLOW_TEXT)
        self.assertIn("sha256sum --check tfplan.sha256", WORKFLOW_TEXT)
        self.assertEqual(
            WORKFLOW_TEXT.count("terraform apply -input=false tfplan"), 1
        )
        apply_command = "terraform apply -input=false tfplan"
        self.assertNotIn("-target", apply_command)

    def test_pm127_apply_verifies_live_iam_objects(self):
        self.assertIn("name: Verify PM-127 Kyverno ECR role", WORKFLOW_TEXT)
        self.assertIn("if: inputs.scope == 'pm127-kyverno-ecr'", WORKFLOW_TEXT)
        self.assertIn("aws iam get-role \\", WORKFLOW_TEXT)
        self.assertIn("aws iam get-role-policy \\", WORKFLOW_TEXT)
        self.assertIn("techx-corp-tf3-kyverno-ecr-read", WORKFLOW_TEXT)


if __name__ == "__main__":
    unittest.main()
