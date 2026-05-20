"""OpenAI-format tool schemas passed to the LLM."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city. Fast response (~200ms).",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string", "description": "City name, e.g. London, Tokyo"}},
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "research_topic",
            "description": "Look up factual information about a topic, including rankings, lists, comparisons, statistics, and summaries. May return generic, cached, truncated, or timeout results.",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string", "description": "Topic or factual question to research, e.g. 'top Indian cities by per capita income'"}},
                "required": ["topic"],
            },
        },
    },
]
