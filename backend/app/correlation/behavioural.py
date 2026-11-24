from dataclasses import dataclass
import re
from typing import Any

from app.correlation.types import FeatureResult
from app.correlation.utils import representation, set_similarity


@dataclass(frozen=True)
class BehaviourEvidence:
    """A source-grounded action or procedure mention."""

    value: str
    evidence_text: str
    start: int
    end: int
    confidence: float = 0.9
    extraction_method: str = "deterministic_behaviour_lexicon_v2"


_BEHAVIOUR_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("initial_access:spear_phishing", (r"\bspear[- ]phish(?:ing|ed)?\b",)),
    ("initial_access:phishing", (r"\bphish(?:ing|ed)?\s+(?:email|message|campaign)\b",)),
    ("initial_access:malicious_attachment", (r"\bmalicious\s+(?:email\s+)?attachment\b",)),
    ("initial_access:exploit_public_facing_application", (
        r"\bexploit(?:ed|ing|ation)?\s+(?:a\s+)?(?:public[- ]facing\s+)?(?:application|vulnerability|flaw)\b",
    )),
    ("initial_access:watering_hole", (r"\bwatering[- ]hole\b",)),
    ("execution:command_line", (r"\bcommand[- ]line\b", r"\bexecut(?:e|ed|ing)\s+(?:a\s+)?command\b")),
    ("execution:script", (r"\b(?:malicious|powershell|python|visual basic)\s+script\b",)),
    ("execution:macro", (r"\b(?:malicious\s+)?macro(?:s)?\b",)),
    ("persistence:scheduled_task", (r"\bscheduled\s+task\b", r"\bcron\s+job\b")),
    ("persistence:registry_run_key", (r"\bregistry\s+(?:run|runonce)\s+key\b",)),
    ("persistence:service", (r"\b(?:installed|created|used)\s+(?:a\s+)?(?:system\s+)?service\b",)),
    ("privilege_escalation:increase_privileges", (
        r"\b(?:escalat(?:e|ed|ing)|obtain(?:ed)?|gain(?:ed)?)\s+(?:local\s+)?(?:administrator|root|system)\s+privileges?\b",
    )),
    ("credential_access:credential_dumping", (
        r"\bcredential\s+dump(?:ing|ed)?\b",
        r"\bdump(?:ed|ing)?\s+credentials?\b",
    )),
    ("credential_access:keylogging", (r"\bkeylog(?:ging|ger|ged)?\b",)),
    ("credential_access:password_theft", (r"\b(?:steal|stole|harvest|dump)\w*\s+(?:user\s+)?passwords?\b",)),
    ("lateral_movement:remote_desktop", (r"\bremote\s+desktop\b",)),
    ("lateral_movement:pass_the_hash", (r"\bpass[- ]the[- ]hash\b",)),
    ("lateral_movement:network_share", (r"\bnetwork\s+share\b", r"\bSMB\s+share\b")),
    ("command_control:beacon", (r"\bbeacon(?:ing|ed)?\b",)),
    ("command_control:command_and_control", (r"\bcommand[- ]and[- ]control\b", r"\bC2\s+(?:server|channel|traffic)\b")),
    ("command_control:dns_tunneling", (r"\bDNS\s+tunnel(?:ing)?\b",)),
    ("collection:screenshot", (r"\b(?:take|capture|captur(?:e|ed|ing))\s+(?:a\s+)?screenshot\b",)),
    ("collection:clipboard", (r"\bclipboard\s+(?:data|contents?)\b",)),
    ("collection:archive_data", (r"\b(?:archive|compress(?:ed|ing)?)\s+(?:the\s+)?(?:stolen\s+)?data\b",)),
    ("exfiltration:exfiltrate_data", (r"\bexfiltrat(?:e|ed|ing)\s+(?:the\s+)?data\b",)),
    ("exfiltration:transfer_data", (r"\btransfer(?:red|ring)?\s+(?:the\s+)?data\s+(?:to|over)\b",)),
    ("defense_evasion:disable_security", (
        r"\bdisable(?:d|s)?\s+(?:the\s+)?(?:security|antivirus|anti[- ]virus|defender)\b",
    )),
    ("defense_evasion:obfuscation", (r"\bobfuscat(?:e|ed|ion|ing)\b",)),
    ("impact:encrypt_files", (r"\bencrypt(?:ed|ing)?\s+(?:the\s+)?files?\b",)),
    ("impact:delete_data", (r"\b(?:delete|deleted|wipe|wiped)\s+(?:the\s+)?data\b",)),
    ("execution:user_execution", (
        r"\b(?:user|victim)\s+(?:opened|clicked|ran|executed)\b",
        r"\bopened\s+(?:the\s+)?(?:document|attachment|file)\b",
    )),
    ("execution:download", (
        r"\bdownload(?:ed|ing)?\s+(?:and\s+)?(?:execut(?:e|ed|ing)|launch(?:e|ed|ing))\b",
        r"\bdownload(?:ed|ing)?\s+(?:a|the)\s+(?:file|payload|malware|tool)\b",
    )),
    ("execution:process_injection", (
        r"\bprocess injection\b",
        r"\binject(?:ed|ing)?\s+(?:code|payload)\s+into\b",
    )),
    ("persistence:startup", (
        r"\b(?:startup|boot)\s+(?:folder|script|entry)\b",
        r"\badded\s+(?:itself|the malware)\s+to\s+(?:startup|autostart)\b",
    )),
    ("credential_access:browser_credentials", (
        r"\b(?:stole|stolen|harvest(?:ed|ing)?)\s+(?:browser|web)\s+(?:credentials|passwords|cookies)\b",
        r"\b(?:browser|web)\s+(?:credentials|passwords|cookies)\b",
    )),
    ("discovery:system_information", (
        r"\b(?:collect(?:ed|ing)?|gather(?:ed|ing)?|enumerat(?:e|ed|ing))\s+system\s+(?:information|details)\b",
        r"\b(?:systeminfo|system information)\b",
    )),
    ("discovery:network_information", (
        r"\b(?:discover(?:ed|ing)?|enumerat(?:e|ed|ing)|scan(?:ned|ning)?)\s+(?:the\s+)?network\b",
        r"\bnetwork\s+reconnaissance\b",
    )),
    ("lateral_movement:remote_services", (
        r"\b(?:used|accessed|connected\s+to)\s+(?:remote|windows)\s+services?\b",
        r"\bremote\s+services?\b",
    )),
    ("collection:file_search", (
        r"\b(?:search(?:ed|ing)?|collect(?:ed|ing)?)\s+(?:for\s+)?(?:documents?|files?)\b",
        r"\bfile\s+search\b",
    )),
    ("exfiltration:staged_data", (
        r"\bstag(?:e|ed|ing)\s+(?:the\s+)?(?:data|files?)\b",
        r"\bcompressed\s+(?:the\s+)?(?:data|files?)\b",
    )),
    ("defense_evasion:clear_artifacts", (
        r"\b(?:clear(?:ed|ing)?|remov(?:e|ed|ing)|delet(?:e|ed|ing))\s+(?:logs?|artifacts?|evidence)\b",
    )),
)


def _evidence_text(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start) + 1, text.rfind("\n", 0, start) + 1)
    right_candidates = [value for value in (text.find(".", end), text.find("\n", end)) if value >= 0]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    return text[left:right].strip()[:1000]


def extract_behaviour_evidence(text: str) -> tuple[BehaviourEvidence, ...]:
    """Extract explicit action phrases without using ATT&CK identifiers.

    The returned values are stable category/procedure keys. Each key is kept
    only when its matching phrase occurs in the report text, and the evidence
    sentence is retained for auditability.
    """
    found: dict[str, BehaviourEvidence] = {}
    for value, patterns in _BEHAVIOUR_PATTERNS:
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                found.setdefault(
                    value,
                    BehaviourEvidence(
                        value=value,
                        evidence_text=_evidence_text(text, match.start(), match.end()),
                        start=match.start(),
                        end=match.end(),
                    ),
                )
                break
    return tuple(found[key] for key in sorted(found))


def behavioural_similarity(first: Any, second: Any) -> FeatureResult:
    score, evidence = set_similarity(representation(first).behaviours, representation(second).behaviours)
    return FeatureResult("behavioural_similarity", 0.5 if score is None else score, score is not None, evidence)
