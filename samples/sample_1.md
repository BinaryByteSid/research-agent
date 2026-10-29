# Compare the top 3 open-source vector databases for a startup building RAG products

## Short answer
Milvus, Weaviate, and Qdrant are prominent open-source vector databases used for RAG products, offering flexible self-hosting and managed cloud options. Milvus handles billion-scale distributed architectures with high operational complexity, Weaviate provides native hybrid search and modular embedding options, and Qdrant excels at filter-heavy retrieval on tight budgets.

## Key findings
- Milvus is an open-source, Kubernetes-native vector database designed for billion-scale distributed similarity search, supporting index types such as IVF, HNSW, and SCANN under the Apache 2.0 license. [S4, S6]
- Weaviate is an open-source, AI-native vector database offering native hybrid search, built-in vectorization modules, and multi-tenancy under the BSD-3 license. [S4, S6]
- Qdrant is an open-source vector database licensed under Apache 2.0 that specializes in filter-heavy retrieval workloads. [S4, S6]
- Milvus setup is noted as complex with multiple components to configure, taking roughly 90 minutes, whereas Qdrant features a straightforward Docker setup and cleaner API. [S5]
- Milvus dominates throughput tests in benchmarks (achieving around 2,400 QPS), followed by Qdrant at 2,100 QPS and Weaviate at 1,500 QPS. [S5]
- Weaviate and Qdrant both offer managed cloud plans starting around $25/mo, providing smaller teams a lower-cost entry point before scaling up. [S1]
- Milvus self-hosted setups carry higher operational complexity and infrastructure requirements, requiring larger EC2 instances. [S5, S6]

## Sources
- [S4] Comparing the best open source vector databases (2026) - https://redis.io/blog/best-open-source-vector-databases-comparison
- [S6] Best Vector Databases 2026: Pinecone vs Weaviate vs Milvus - https://iternal.ai/insights/best-vector-databases-2026
- [S5] I Tested 5 Vector Databases at Scale. Here’s What Actually Matters. - https://medium.com/@officialpreksha2166/i-tested-5-vector-databases-at-scale-heres-what-actually-matters-93fb997e21b0
- [S1] Vector Database Comparison: Best Picks by Use Case - https://pecollective.com/tools/best-vector-databases

## Confidence: medium (0.85)
- 7 cited finding(s) drawn from 4 independent domain(s)
- 100% of sub-questions had usable sources
- 100% of drafted findings passed citation checks
- Score is a heuristic and has not been calibrated against ground truth
- 57% of findings rely on one source (S6)

## Limitations
- The selection of Milvus, Weaviate, and Qdrant as the top 3 open-source vector databases is based on frequency and favorability of mentions across the provided vendor and review sources.
- Benchmark numbers and performance metrics like QPS and indexing speeds can vary based on test configuration and hardware, and some sources originate from commercial entities in the vector database space.
- Most findings depend on a single source (S6); independent confirmation is limited.

## Suggested next steps
- Benchmark Qdrant, Weaviate, and Milvus using a representative dataset with your exact embedding dimensions and metadata filters.
- Evaluate internal DevOps capacity to determine whether your startup can support Kubernetes orchestration for Milvus or prefer simpler managed cloud entry points.
- Test hybrid search and filtering behavior under concurrent read updates to see which database matches your application's retrieval requirements.
