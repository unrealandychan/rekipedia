```mermaid
classDiagram
  BaseModel <|-- AnalysisResult
  ABC <|-- BaseExtractor
  ABC <|-- BaseRunner
  BaseModel <|-- BizDomainGraph
  VectorStore <|-- ChromaStore
  BaseExtractor <|-- ConfigExtractor
  BaseRunner <|-- DockerSandboxRunner
  BaseModel <|-- DomainNode
  VectorStore <|-- FaissStore
  BaseModel <|-- FileManifest
  BaseModel <|-- FlowNode
  BaseExtractor <|-- GoExtractor
  BaseExtractor <|-- JavaExtractor
  Protocol <|-- LLMCaller
  BaseModel <|-- LLMConfig
  BaseRunner <|-- LocalRunner
  BaseExtractor <|-- PythonExtractor
  VectorStore <|-- QdrantStore
  BaseModel <|-- RationaleNote
  BaseModel <|-- Relationship
```
