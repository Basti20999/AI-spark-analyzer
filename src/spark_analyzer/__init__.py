"""AI Spark Analyzer.

Fetches a spark profiler report (https://spark.lucko.me), parses the call
tree, computes self-time / plugin attribution / lag-spike windows, and uses
Claude to produce an expert diagnosis of what is causing lag spikes.
"""

from .models import Profile, ThreadProfile, StackNode, WindowStats

__version__ = "0.1.0"

__all__ = ["Profile", "ThreadProfile", "StackNode", "WindowStats", "__version__"]
