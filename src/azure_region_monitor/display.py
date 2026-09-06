"""Shared reader-facing names; identifiers remain available in evidence."""

from __future__ import annotations

import re


def region_name(region: str) -> str:
    words = (
        "southafrica", "newzealand", "switzerland", "netherlands", "australia",
        "indonesia", "singapore", "malaysia", "germany", "norway", "sweden",
        "denmark", "finland", "belgium", "austria", "canada", "brazil", "mexico",
        "france", "poland", "israel", "taiwan", "greece", "portugal", "italy",
        "spain", "chile", "japan", "korea", "china", "india", "qatar", "jio",
        "europe", "asia", "central", "north", "south", "east", "west",
        "euap", "stg", "uae", "uk", "us",
    )
    tokens = re.findall("|".join(words) + r"|\d+", region.lower())
    if "".join(tokens) != region.lower():
        return region
    names = {
        "southafrica": "South Africa", "newzealand": "New Zealand",
        "us": "US", "uk": "UK", "uae": "UAE", "euap": "EUAP", "stg": "STG",
    }
    return " ".join(names.get(token, token.title()) for token in tokens)


def plain_feature_name(feature: str) -> str:
    if feature.startswith("aiModels."):
        parts = feature.removeprefix("aiModels.").split(".")
        publisher = parts[0] if parts else "unknown"
        model_parts = parts[1:-1] if len(parts) > 2 else parts[1:]
        model = ".".join(model_parts) or "unknown"
        version = parts[-1] if len(parts) > 2 else ""
        publisher_name = {
            "anthropic": "Anthropic", "meta": "Meta", "microsoft": "Microsoft",
            "moonshotai": "Moonshot AI", "openai": "OpenAI", "xai": "xAI",
        }.get(publisher.lower(), publisher)
        version_text = f" (version {version})" if version else ""
        return f"{display_model_name(model)} model from {publisher_name}{version_text}"
    if feature.startswith("vmSkus."):
        sku = " ".join(part.capitalize() for part in feature.removeprefix("vmSkus.").split("."))
        return f"{sku} VM size"
    if feature.startswith("kubernetesVersions."):
        return f"AKS {feature.removeprefix('kubernetesVersions.')}"
    if feature.startswith("extensionTypes."):
        return f"{feature.removeprefix('extensionTypes.')} AKS extension"
    if feature.startswith("runtimes."):
        return f"{feature.removeprefix('runtimes.').replace('.', ' ')} Functions runtime"
    if feature.startswith("containerApps."):
        return f"{feature.removeprefix('containerApps.')} Container Apps capability"
    return feature


def display_model_name(model: str) -> str:
    display_parts = []
    for part in model.split("-"):
        lowered = part.lower()
        if lowered == "gpt":
            display_parts.append("GPT")
        elif re.fullmatch(r"k\d+", lowered):
            display_parts.append(lowered.upper())
        elif lowered in {"astra", "claude", "fable", "haiku", "kimi", "mythos", "opus", "sonnet"}:
            display_parts.append(lowered.title())
        else:
            display_parts.append(part)
    if len(display_parts) >= 2 and display_parts[0] == "GPT":
        return "-".join(display_parts[:2]) + (
            f" {' '.join(display_parts[2:])}" if len(display_parts) > 2 else ""
        )
    return " ".join(display_parts)
