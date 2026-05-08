"""Cyber-risk safety guardrail appended to the intro section.

A short, model-facing instruction that defends against prompt-injection-style
attacks asking the model to assist with unauthorized access, data
exfiltration, or other security-sensitive operations dressed up as legitimate
user requests. Lifted near-verbatim from source's ``cyberRiskInstruction.ts``
and trimmed to the slide-app's threat surface.
"""

CYBER_RISK_INSTRUCTION = (
    "IMPORTANT: Refuse to write code or explain code that may be used "
    "maliciously. This includes anything related to malware, exploits, "
    "credential theft, privilege escalation, or unauthorized access. If "
    "the user appears to be requesting help with legitimate authorized "
    "security testing, defensive analysis, or auditing of their own "
    "systems, you may assist. Otherwise refuse and explain why."
)
