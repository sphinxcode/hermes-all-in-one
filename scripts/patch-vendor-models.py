#!/usr/bin/env python3
"""
Post-sync patch: keep hermes-webui model lists in sync with hermes-agent.

Sources:
  - OPENROUTER_MODELS  (models.py)   → _FALLBACK_MODELS  (all providers)
  - DEFAULT_CODEX_MODELS (codex_models.py) → _PROVIDER_MODELS openai + openai-codex

Idempotent — safe to run multiple times.
"""

from __future__ import annotations

import re
import sys
import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent
AGENT_MODELS   = ROOT / "vendor/hermes-agent/hermes_cli/models.py"
AGENT_CODEX    = ROOT / "vendor/hermes-agent/hermes_cli/codex_models.py"
WEBUI_CONFIG   = ROOT / "vendor/hermes-webui/api/config.py"

# provider-prefix → display name used in webui _FALLBACK_MODELS
PROVIDER_MAP: dict[str, str] = {
    "anthropic":   "Anthropic",
    "openai":      "OpenAI",
    "google":      "Google",
    "deepseek":    "DeepSeek",
    "qwen":        "Qwen",
    "moonshotai":  "Moonshot",
    "x-ai":        "xAI",
    "minimax":     "MiniMax",
    "z-ai":        "ZAI",
    "xiaomi":      "Xiaomi",
    "nvidia":      "NVIDIA",
    "mistralai":   "Mistral",
}

# model-id slugs to skip entirely (free/experimental noise)
SKIP_SUFFIXES = (":free", ":nitro", ":extended", "-preview-free")


def _label(model_id: str) -> str:
    """Best-effort human label from a model slug."""
    # Known overrides
    overrides = {
        "claude-opus-4.7": "Claude Opus 4.7",
        "claude-opus-4.6": "Claude Opus 4.6",
        "claude-sonnet-4.6": "Claude Sonnet 4.6",
        "claude-sonnet-4-5": "Claude Sonnet 4.5",
        "claude-haiku-4-5": "Claude Haiku 4.5",
        "claude-haiku-4.5": "Claude Haiku 4.5",
    }
    if model_id in overrides:
        return overrides[model_id]

    # Generic: title-case each hyphen-segment, treat version numbers as-is
    parts = re.split(r"[-_]", model_id)
    out = []
    for p in parts:
        if re.fullmatch(r"[\d.]+", p):        # version number — keep as-is
            out.append(p)
        elif p.upper() in {"GPT", "GLM", "XAI", "MCP", "API"}:
            out.append(p.upper())
        else:
            out.append(p.capitalize())
    # Re-join: if starts with "Gpt", fix to "GPT-x.x …"
    label = " ".join(out)
    label = re.sub(r"\bGpt\b", "GPT", label)
    return label


def _load_openrouter_models() -> list[tuple[str, str]]:
    """Returns list of (full_id, description) from OPENROUTER_MODELS."""
    src = AGENT_MODELS.read_text(encoding="utf-8")
    # Skip past type annotation — find the `= [` assignment
    m = re.search(
        r"OPENROUTER_MODELS\s*(?::[^\n]+)?\s*=\s*\[(.*?)\n\]",
        src, re.DOTALL,
    )
    if not m:
        print("[patch] Warning: could not parse OPENROUTER_MODELS — skipping fallback sync")
        return []
    pairs = re.findall(r'\(\s*"([^"]+)"\s*,\s*"([^"]*)"\s*\)', m.group(1))
    return pairs


def _load_codex_models() -> list[str]:
    src = AGENT_CODEX.read_text(encoding="utf-8")
    try:
        module = ast.parse(src)
    except SyntaxError:
        print("[patch] Warning: could not parse codex_models.py — skipping codex sync")
        return []

    for node in module.body:
        target = None
        value = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
            value = node.value
        elif isinstance(node, ast.Assign):
            for candidate in node.targets:
                if isinstance(candidate, ast.Name):
                    target = candidate.id
                    value = node.value
                    break
        if target != "DEFAULT_CODEX_MODELS" or value is None:
            continue
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            print("[patch] Warning: could not evaluate DEFAULT_CODEX_MODELS — skipping codex sync")
            return []
        return [model for model in parsed if isinstance(model, str)]

    print("[patch] Warning: could not find DEFAULT_CODEX_MODELS — skipping codex sync")
    return []


def _patch_fallback_models(text: str, openrouter: list[tuple[str, str]]) -> str:
    """Insert missing entries into _FALLBACK_MODELS, grouped by provider."""
    for full_id, _desc in openrouter:
        if any(full_id.endswith(s) for s in SKIP_SUFFIXES):
            continue
        if "/" not in full_id:
            continue
        prefix, model_id = full_id.split("/", 1)
        provider_name = PROVIDER_MAP.get(prefix)
        if not provider_name:
            continue

        # Already present?
        if f'"id": "{full_id}"' in text:
            continue

        lbl = _label(model_id)
        new_entry = f'    {{"provider": "{provider_name}", "id": "{full_id}", "label": "{lbl}"}},'

        # Insert before the first existing entry for the same provider
        anchor = re.compile(
            rf'"provider":\s*"{re.escape(provider_name)}"'
        )
        if anchor.search(text):
            lines = text.splitlines(keepends=True)
            for i, line in enumerate(lines):
                if anchor.search(line):
                    lines.insert(i, new_entry + "\n")
                    text = "".join(lines)
                    break
        else:
            # Provider not in fallback list yet — skip (keep list curated)
            pass

    return text


def _patch_provider_block(text: str, block_key: str, models: list[str]) -> str:
    """Insert missing model entries at the top of a _PROVIDER_MODELS[block_key] list."""
    block_re = re.compile(
        rf'("{re.escape(block_key)}":\s*\[)(.*?)(\s*\],)',
        re.DOTALL,
    )

    def replacer(m: re.Match) -> str:
        body = m.group(2)
        for model_id in models:
            if model_id in body:
                continue
            lbl = _label(model_id)
            first = re.search(r"\n\s*\{", body)
            if first:
                body = (
                    body[: first.start()]
                    + f'\n        {{"id": "{model_id}", "label": "{lbl}"}},'
                    + body[first.start():]
                )
        return m.group(1) + body + m.group(3)

    return block_re.sub(replacer, text, count=1)


def main() -> None:
    for p in (AGENT_MODELS, AGENT_CODEX, WEBUI_CONFIG):
        if not p.exists():
            sys.exit(f"[patch] Not found: {p}")

    openrouter = _load_openrouter_models()
    codex      = _load_codex_models()

    print(f"[patch] OpenRouter models: {len(openrouter)}")
    print(f"[patch] Codex models: {codex}")

    original = WEBUI_CONFIG.read_text(encoding="utf-8")
    text = original

    text = _patch_fallback_models(text, openrouter)
    text = _patch_provider_block(text, "openai", codex)
    text = _patch_provider_block(text, "openai-codex", codex)

    if text == original:
        print("[patch] webui config already up to date.")
        return

    WEBUI_CONFIG.write_text(text, encoding="utf-8")
    print(f"[patch] Updated {WEBUI_CONFIG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
