"""Version identifiers recorded in every receipt."""

CODE_VERSION = "0.13.0"
REVIEW_SCHEMA_VERSION = "forgevigil.review.v1"
BACKUP_SCHEMA_VERSION = "forgevigil.backup.v1"
REQUEST_SCHEMA_VERSION = "forgevigil.request.v1"
ASSESSMENT_SCHEMA_VERSION = "forgevigil.assessment.v3"
RECEIPT_SCHEMA_VERSION = "forgevigil.receipt.v4"  # v4: input_digest may be hmac-sha256
POLICY_VERSION = "cp04.policy.v1"
FIXTURE_VERSION = "cp01.fixtures.v1"
# Fixture assessors use no prompt. Live assessors report their own prompt version.
PROMPT_VERSION = "none:fixture-mode"
STORE_SCHEMA_VERSION = "3"
