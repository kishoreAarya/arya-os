"""Platform adapters package.

Mirrors the app/providers/ structure: each platform (YouTube,
Instagram, TikTok, etc.) gets its own module implementing the
PlatformAdapter ABC. The registry (app/platforms/registry.py) maps
platform names to adapter classes, same pattern as AGENT_REGISTRY.
"""
