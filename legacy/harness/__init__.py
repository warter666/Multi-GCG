"""Local agent harness: run a real episode, record a real trace, judge it afterwards.

Everything here is execution. Whether the attack succeeded is decided later, by applying
predicates to the recorded trace — never inside the loop.
"""

__all__ = ["env", "loop", "trace"]
