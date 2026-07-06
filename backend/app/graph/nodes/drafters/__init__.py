"""
Drafter modules for the Redline node (Node 6).

redline_drafter.py generates safer replacement language for a redline-eligible
clause via a single generative LLM call. Like scorers/__init__.py, this package
init hosts no shared helper — redline_drafter.py reuses format_evidence from the
validators package (a dependency-free renderer of the 001 evidence shape) rather
than redefining it.
"""
