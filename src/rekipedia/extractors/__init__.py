"""rekipedia.extractors package."""
from rekipedia.extractors.config_extractor import ConfigExtractor
from rekipedia.extractors.python_extractor import PythonExtractor
from rekipedia.extractors.typescript_extractor import TypeScriptExtractor

ALL_EXTRACTORS = [PythonExtractor(), TypeScriptExtractor(), ConfigExtractor()]

__all__ = ["ALL_EXTRACTORS", "PythonExtractor", "TypeScriptExtractor", "ConfigExtractor"]
