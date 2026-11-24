import json

from stix2 import AttackPattern, Bundle, IntrusionSet, Relationship

from app.attack.dataset import AttackDataset
from app.attack.service import find_mapping_candidates


def fixture_dataset() -> AttackDataset:
    technique = AttackPattern(
        name="Command and Scripting Interpreter",
        description="Use command interpreters.",
        external_references=[
            {"source_name": "mitre-attack", "external_id": "T1059", "url": "https://attack.mitre.org/techniques/T1059/"}
        ],
        kill_chain_phases=[{"kill_chain_name": "mitre-attack", "phase_name": "execution"}],
        x_mitre_aliases=["Command Shell"],
        x_mitre_version="15.0",
        allow_custom=True,
    )
    group = IntrusionSet(
        name="APT28",
        description="A known intrusion set.",
        external_references=[
            {"source_name": "mitre-attack", "external_id": "G####"}
        ],
    )
    relationship = Relationship(
        relationship_type="uses",
        source_ref=group.id,
        target_ref=technique.id,
    )
    payload = json.loads(Bundle(technique, group, relationship, allow_custom=True).serialize())
    return AttackDataset.from_payload(payload, version="enterprise-attack-test")


def test_official_bundle_parser_supports_techniques_tactics_groups_and_relationships() -> None:
    dataset = fixture_dataset()
    assert dataset.version == "enterprise-attack-test"
    assert dataset.objects["T1059"].tactics == ("execution",)
    assert dataset.objects["T1059"].aliases == ("Command Shell",)
    assert dataset.uses_relationships["G####"] == {"T1059"}


def test_mapping_distinguishes_confirmed_reference_and_inferred_alias() -> None:
    dataset = fixture_dataset()
    confirmed, unsupported = find_mapping_candidates(
        "APT28 used T1059 during the operation.", dataset, ["APT28"]
    )
    assert unsupported == []
    assert len(confirmed) == 1
    assert confirmed[0].status == "confirmed_reference"
    assert confirmed[0].method == "explicit_attack_reference"

    inferred, _ = find_mapping_candidates(
        "The actor used command shell scripting.", dataset, []
    )
    assert inferred[0].status == "inferred"
    assert inferred[0].method == "lexical_attack_name"


def test_unsupported_identifier_is_not_claimed_as_a_mapping() -> None:
    candidates, unsupported = find_mapping_candidates(
        "The report references T9999.", fixture_dataset()
    )
    assert candidates == []
    assert unsupported == ["T9999"]


def test_explicit_only_mapping_does_not_infer_from_names_or_entities() -> None:
    candidates, unsupported = find_mapping_candidates(
        "APT28 used Command Shell scripting.",
        fixture_dataset(),
        ["APT28"],
        explicit_only=True,
    )
    assert candidates == []
    assert unsupported == []
