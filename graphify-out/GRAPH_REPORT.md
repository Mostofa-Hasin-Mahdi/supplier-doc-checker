# Graph Report - .  (2026-11-04)

## Corpus Check
- Corpus is ~861 words - fits in a single context window. You may not need a graph.

## Summary
- 25 nodes · 21 edges · 5 communities (2 shown, 3 thin omitted)
- Extraction: 43% EXTRACTED · 57% INFERRED · 0% AMBIGUOUS · INFERRED: 12 edges (avg confidence: 0.86)
- Token cost: 1,200 input · 850 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Procurement Rules & Packs|Procurement Rules & Packs]]
- [[_COMMUNITY_Architecture & Policy Governance|Architecture & Policy Governance]]
- [[_COMMUNITY_Sanity Testing Suite|Sanity Testing Suite]]
- [[_COMMUNITY_Supplier Check Package Core|Supplier Check Package Core]]
- [[_COMMUNITY_Test Suite Setup|Test Suite Setup]]

## God Nodes (most connected - your core abstractions)
1. `Supplier Document Rules` - 14 edges
2. `test_package_version()` - 2 edges
3. `Verdict: NEEDS_REVIEW Rules` - 2 edges
4. `AGENTS Standing Rules` - 2 edges
5. `Never Guess Policy` - 2 edges
6. `Supplier Document Checker package.` - 1 edges
7. `Test suite for supplier-check.` - 1 edges
8. `Sanity test verifying package version is defined.` - 1 edges
9. `Verdict: REJECT Rules` - 1 edges
10. `Verdict: APPROVE Rules` - 1 edges

## Surprising Connections (you probably didn't know these)
- `Never Guess Policy` --semantically_similar_to--> `Verdict: NEEDS_REVIEW Rules`  [INFERRED] [semantically similar]
  AGENTS.md → data/company-rules.md
- `Procurement Rules Configuration` --conceptually_related_to--> `Supplier Document Rules`  [INFERRED]
  config/rules.yaml → data/company-rules.md
- `Padma Textile Mills Ltd (Pack 01)` --references--> `Supplier Document Rules`  [INFERRED]
  data/supplier-pack-01.pdf → data/company-rules.md
- `Jamuna Trims and Accessories (Pack 02)` --references--> `Supplier Document Rules`  [INFERRED]
  data/supplier-pack-02.pdf → data/company-rules.md
- `Karnaphuli Yarn Traders (Pack 03)` --references--> `Supplier Document Rules`  [INFERRED]
  data/supplier-pack-03.pdf → data/company-rules.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **3-Way Verdict Evaluation** — concept_verdict_approve, concept_verdict_reject, concept_verdict_needs_review [EXTRACTED 1.00]

## Communities (5 total, 3 thin omitted)

### Community 0 - "Procurement Rules & Packs"
Cohesion: 0.14
Nodes (14): Verdict: APPROVE Rules, Verdict: REJECT Rules, Procurement Rules Configuration, Supplier Document Rules, Padma Textile Mills Ltd (Pack 01), Jamuna Trims and Accessories (Pack 02), Karnaphuli Yarn Traders (Pack 03), Surma Packaging Industries (Pack 04) (+6 more)

### Community 1 - "Architecture & Policy Governance"
Cohesion: 0.50
Nodes (4): AGENTS Standing Rules, Fixed LangGraph Linear Pipeline, Never Guess Policy, Verdict: NEEDS_REVIEW Rules

## Knowledge Gaps
- **14 isolated node(s):** `Verdict: REJECT Rules`, `Verdict: APPROVE Rules`, `Fixed LangGraph Linear Pipeline`, `Procurement Rules Configuration`, `Padma Textile Mills Ltd (Pack 01)` (+9 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Supplier Document Rules` connect `Procurement Rules & Packs` to `Architecture & Policy Governance`?**
  _High betweenness centrality (0.471) - this node is a cross-community bridge._
- **Why does `Verdict: NEEDS_REVIEW Rules` connect `Architecture & Policy Governance` to `Procurement Rules & Packs`?**
  _High betweenness centrality (0.152) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `Supplier Document Rules` (e.g. with `Procurement Rules Configuration` and `Padma Textile Mills Ltd (Pack 01)`) actually correct?**
  _`Supplier Document Rules` has 11 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Supplier Document Checker package.`, `Test suite for supplier-check.`, `Sanity test verifying package version is defined.` to the rest of the system?**
  _17 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Procurement Rules & Packs` be split into smaller, more focused modules?**
  _Cohesion score 0.14285714285714285 - nodes in this community are weakly interconnected._