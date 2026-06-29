"""Data model for a parsed spark report.

spark's sampling profiler records, for every thread, a call tree of
``StackTraceNode`` frames. Each frame carries a ``times`` array (one value per
profiling time-window) measuring wall time accumulated in that frame. The
*total* time of a frame includes its children; the *self* time is what's left
after subtracting the children — that's where the CPU actually went.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StackNode:
    """A single frame (method) in a thread's call tree."""

    class_name: str
    method_name: str
    line_number: int = 0
    method_desc: str = ""
    times: list[float] = field(default_factory=list)
    children: list["StackNode"] = field(default_factory=list)
    # Plugin / mod this frame was attributed to by spark, if known.
    source: str | None = None

    @property
    def total_time(self) -> float:
        """Wall time spent in this frame and everything it called."""
        return float(sum(self.times))

    @property
    def self_time(self) -> float:
        """Wall time spent in this frame itself, excluding callees."""
        child_total = sum(c.total_time for c in self.children)
        return max(0.0, self.total_time - child_total)

    @property
    def label(self) -> str:
        if self.class_name and self.method_name:
            return f"{self.class_name}.{self.method_name}"
        return self.method_name or self.class_name or "(unknown)"


@dataclass
class ThreadProfile:
    """A profiled thread and its root call frames."""

    name: str
    roots: list[StackNode] = field(default_factory=list)

    @property
    def total_time(self) -> float:
        return float(sum(r.total_time for r in self.roots))


@dataclass
class WindowStats:
    """Per-time-window server statistics (TPS, MSPT, counts)."""

    window: int
    ticks: int = 0
    tps: float = 0.0
    mspt_median: float = 0.0
    mspt_max: float = 0.0
    cpu_process: float = 0.0
    cpu_system: float = 0.0
    players: int = 0
    entities: int = 0
    chunks: int = 0
    duration: int = 0


@dataclass
class Profile:
    """A fully parsed spark report."""

    threads: list[ThreadProfile] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    window_stats: list[WindowStats] = field(default_factory=list)
    platform: dict = field(default_factory=dict)
    source_type: str = "unknown"  # sampler | health | unknown
    raw: dict = field(default_factory=dict)
