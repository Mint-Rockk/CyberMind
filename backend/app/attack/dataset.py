from dataclasses import dataclass, field
from typing import Any

import httpx
import stix2

OFFICIAL_ATTACK_DATASET_URL = (
    "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/"
    "enterprise-attack/enterprise-attack.json"
)


@dataclass(frozen=True)
class AttackObject:
    external_id: str
    object_type: str
    name: str
    description: str
    aliases: tuple[str, ...] = ()
    tactics: tuple[str, ...] = ()
    version: str | None = None
    references: tuple[dict[str, Any], ...] = ()


@dataclass
class AttackDataset:
    version: str
    objects: dict[str, AttackObject] = field(default_factory=dict)
    uses_relationships: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], version: str | None = None) -> "AttackDataset":
        if payload.get("type") != "bundle" or not isinstance(payload.get("objects"), list):
            raise ValueError("ATT&CK dataset must be a STIX bundle with an objects list")
        try:
            stix2.parse(payload, allow_custom=True)
        except Exception as exc:
            raise ValueError("ATT&CK dataset failed STIX validation") from exc
        objects: dict[str, AttackObject] = {}
        relationships: dict[str, set[str]] = {}
        stix_to_external: dict[str, str] = {}
        raw_relationships: list[tuple[str, str]] = []
        detected_versions: list[str] = []
        collection_versions: list[str] = []
        for item in payload["objects"]:
            if item.get("type") == "x-mitre-collection" and item.get("x_mitre_version"):
                collection_versions.append(str(item["x_mitre_version"]))
                continue
            if item.get("type") == "relationship":
                if item.get("relationship_type") == "uses":
                    raw_relationships.append(
                        (item.get("source_ref", ""), item.get("target_ref", ""))
                    )
                continue
            if item.get("type") not in {
                "attack-pattern", "malware", "tool", "intrusion-set", "campaign"
            }:
                continue
            external_id = next(
                (
                    reference.get("external_id")
                    for reference in item.get("external_references", [])
                    if reference.get("source_name") == "mitre-attack"
                    and reference.get("external_id")
                ),
                None,
            )
            if not external_id:
                continue
            if item.get("id"):
                stix_to_external[item["id"]] = external_id
            item_version = item.get("x_mitre_version")
            if item_version:
                detected_versions.append(str(item_version))
            objects[external_id] = AttackObject(
                external_id=external_id,
                object_type=item["type"],
                name=str(item.get("name") or external_id),
                description=str(item.get("description") or ""),
                aliases=tuple(item.get("x_mitre_aliases") or item.get("aliases") or ()),
                tactics=tuple(
                    phase.get("phase_name", "")
                    for phase in item.get("kill_chain_phases", [])
                    if phase.get("kill_chain_name") == "mitre-attack"
                ),
                version=str(item_version) if item_version else None,
                references=tuple(item.get("external_references") or ()),
            )
        for source_ref, target_ref in raw_relationships:
            source_external = stix_to_external.get(source_ref)
            target_external = stix_to_external.get(target_ref)
            if source_external and target_external:
                relationships.setdefault(source_external, set()).add(target_external)
        dataset_version = version or (
            f"enterprise-attack-{collection_versions[0]}"
            if collection_versions
            else (
                f"enterprise-attack-{max(detected_versions)}"
                if detected_versions
                else "enterprise-attack-unknown"
            )
        )
        return cls(version=dataset_version, objects=objects, uses_relationships=relationships)


async def download_official_dataset(
    url: str = OFFICIAL_ATTACK_DATASET_URL,
) -> AttackDataset:
    timeout = httpx.Timeout(60)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("Official ATT&CK response was not valid JSON") from exc
    return AttackDataset.from_payload(payload)
