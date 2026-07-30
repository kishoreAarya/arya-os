"""Prompts for LLM-based learning feedback enhancement.

These prompts are used when the rule-based LearningAnalyzer needs
augmentation from an LLM. They follow the same pattern as other
agent prompts in the repository (e.g., ScriptAgent, PromptAgent).

Usage:
    from app.prompts.learning_feedback import build_learning_analysis_prompt
    prompt = build_learning_analysis_prompt(analytics_input)
    exec_result = await execution_engine.execute(
        capability=Capability.TEXT_GENERATION,
        call=build_text_generation_call(prompt),
    )
"""

from app.models.learning import AnalyticsInput


def build_learning_analysis_prompt(data: AnalyticsInput) -> str:
    """Build a prompt for LLM-based performance analysis.

    The LLM receives structured analytics data and produces insights
    that complement the rule-based scoring from LearningAnalyzer.
    """
    lines = [
        "You are a senior content strategist analyzing YouTube video performance.",
        "",
        "VIDEO METRICS:",
        f"  Title: {data.title}",
        f"  Topic: {data.topic or 'Unknown'}",
        f"  Views: {data.views:,}",
    ]

    if data.impressions is not None:
        lines.append(f"  Impressions: {data.impressions:,}")
    if data.ctr is not None:
        lines.append(f"  CTR: {data.ctr:.1%}")
    if data.average_view_duration_seconds is not None:
        lines.append(f"  Avg View Duration: {data.average_view_duration_seconds:.0f}s")
    if data.average_view_percentage is not None:
        lines.append(f"  Avg View %: {data.average_view_percentage:.0%}")
    if data.likes:
        lines.append(f"  Likes: {data.likes:,}")
    if data.comments:
        lines.append(f"  Comments: {data.comments:,}")
    if data.shares:
        lines.append(f"  Shares: {data.shares:,}")
    if data.subscribers_gained:
        lines.append(f"  Subscribers Gained: {data.subscribers_gained:,}")

    lines.extend([
        "",
        "THUMBNAIL:",
        f"  {data.thumbnail_description or 'No description provided'}",
        "",
        "SCRIPT SUMMARY:",
        f"  {data.script_summary or 'No summary provided'}",
        "",
        "TASK:",
        "Analyze this video's performance and identify:",
        "1. What worked well (specific, actionable observations)",
        "2. What could be improved (concrete suggestions)",
        "3. Reusable patterns for future videos (format as: CATEGORY: insight)",
        "4. One surprising insight that the numbers reveal",
        "",
        "Format your response as:",
        "STRENGTHS:",
        "- ...",
        "",
        "WEAKNESSES:",
        "- ...",
        "",
        "PATTERNS:",
        "- CATEGORY: specific pattern with evidence",
        "",
        "SURPRISING_INSIGHT:",
        "- ...",
    ])

    return "\n".join(lines)


def build_pattern_extraction_prompt(
    title: str,
    topic: str | None,
    patterns: list[str],
) -> str:
    """Build a prompt for extracting structured reusable patterns.

    Takes raw pattern strings and asks the LLM to structure them
    into the ReusablePattern format.
    """
    lines = [
        "You are a pattern extraction engine. Convert the following",
        "raw observations into structured reusable patterns.",
        "",
        f"VIDEO: {title}",
        f"TOPIC: {topic or 'General'}",
        "",
        "RAW OBSERVATIONS:",
    ]
    for p in patterns:
        lines.append(f"  - {p}")

    lines.extend([
        "",
        "For each observation, produce a structured pattern:",
        "",
        "FORMAT:",
        "CATEGORY: [topic|script|thumbnail|prompt|title]",
        "PATTERN: [concise, reusable insight]",
        "EVIDENCE: [specific metric or observation]",
        "CONFIDENCE: [0.0-1.0]",
        "CONDITIONS: [when this pattern applies]",
        "---",
        "",
        "Be specific. Generic advice like 'make good content' is useless.",
        "Focus on what the NUMBERS actually reveal.",
    ])

    return "\n".join(lines)


def build_comparative_analysis_prompt(
    video_a: AnalyticsInput,
    video_b: AnalyticsInput,
) -> str:
    """Build a prompt for comparing two videos to find differential patterns.

    Useful for A/B testing: why did video A outperform video B?
    """
    lines = [
        "You are comparing two videos to understand why one outperformed the other.",
        "",
        "VIDEO A (Better Performer):",
        f"  Title: {video_a.title}",
        f"  Views: {video_a.views:,}",
        f"  CTR: {video_a.ctr:.1%}" if video_a.ctr else "  CTR: N/A",
        f"  Retention: {video_a.average_view_percentage:.0%}" if video_a.average_view_percentage else "  Retention: N/A",
        "",
        "VIDEO B (Lower Performer):",
        f"  Title: {video_b.title}",
        f"  Views: {video_b.views:,}",
        f"  CTR: {video_b.ctr:.1%}" if video_b.ctr else "  CTR: N/A",
        f"  Retention: {video_b.average_view_percentage:.0%}" if video_b.average_view_percentage else "  Retention: N/A",
        "",
        "TASK:",
        "Identify the most likely cause of the performance difference.",
        "Focus on ONE primary factor and support it with the metrics.",
        "",
        "FORMAT:",
        "PRIMARY_FACTOR: [the one thing that most explains the difference]",
        "EVIDENCE: [specific metric comparison]",
        "RECOMMENDATION: [what to replicate from A, what to avoid from B]",
    ]

    return "\n".join(lines)
