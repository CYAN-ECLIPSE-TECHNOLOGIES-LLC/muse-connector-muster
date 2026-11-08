"""Synthetic fixtures for the connector integration tests.

All data is invented for testing. Domains use the reserved
`test.example` TLD and phone numbers use the reserved 555-0100
range, so nothing here can collide with a real person or account.
"""

PROVENANCE = {
    "platform": "test-suite",
    "platform_object_id": "fixture",
    "source": "owner_entry",
    "observed_at": "2026-01-01T00:00:00Z",
    "adapter_version": "connector-tests-0.1.0",
}

DATA_RIGHTS = {
    "source_account": "connector-test-fixtures",
    "legal_basis": "account-owner instruction",
    "method": "fixture",
    "pii_class": "strictest",
}


def _record(kind, record_id, fields):
    return {
        "kind": kind,
        "record_id": record_id,
        "external_ids": {"test-suite": record_id},
        "fields": fields,
        "field_provenance": {name: dict(PROVENANCE) for name in fields},
        "data_rights": dict(DATA_RIGHTS),
    }


def person_a():
    return _record("person", "person-test-a", {
        "name": "Alpha Tester",
        "emails": ["alpha.tester@test.example"],
        "phone": "+1-555-010-9876",
        "ssn": "123-45-6789",
        "role": "Integration test persona A",
    })


def person_b():
    # Same email and phone as person A: a merge candidate pair.
    return _record("person", "person-test-b", {
        "name": "A. Tester",
        "emails": ["alpha.tester@test.example"],
        "phone": "+1-555-010-9876",
        "timezone": "UTC",
    })


def ticket():
    # No resolution field: a reply draft must either cite what is on
    # the record or mark the resolution MISSING_FACT, never invent one.
    return _record("ticket", "ticket-test-1", {
        "subject": "Integration test ticket",
        "status": "open",
    })
