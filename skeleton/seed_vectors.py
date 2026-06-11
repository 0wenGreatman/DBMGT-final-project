"""
TransitFlow — pgvector Policy Document Seeder
Run once after starting Docker:
    python skeleton/seed_vectors.py

This script:
  1. Loads policy documents directly from train-mock-data/ JSON files
  2. Embeds each document using the configured LLM provider
  3. Stores the text + vector in PostgreSQL (policy_documents table)

Note: Gemini free tier has ~1500 requests/minute — this script makes ~13 calls, well within limits.

Students: To extend the assistant's knowledge, add entries to the JSON files in
train-mock-data/ and re-run this script.
"""

import json
import os
import sys
import time

sys.path.insert(0, ".")

from skeleton.llm_provider import llm
from databases.relational.queries import store_policy_document

_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "train-mock-data")
)


def _load(filename):
    with open(os.path.join(_DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def _text(data):
    return json.dumps(data, indent=2, ensure_ascii=False)


def build_documents():
    docs = []

    # refund_policy.json — one document per policy entry
    for policy in _load("refund_policy.json"):
        docs.append({
            "title": policy["label"],
            "category": "refund",
            "source_file": "refund_policy.json",
            "content": _text(policy),
        })

    # ticket_types.json — one document per ticket type
    for tt in _load("ticket_types.json"):
        docs.append({
            "title": f"Ticket Type: {tt['display_name']}",
            "category": "booking",
            "source_file": "ticket_types.json",
            "content": _text(tt),
        })

    # booking_rules.json — one document per network section
    br = _load("booking_rules.json")
    for section in ("national_rail", "metro", "general_rules"):
        if section in br:
            docs.append({
                "title": f"Booking Rules — {section.replace('_', ' ').title()}",
                "category": "booking",
                "source_file": "booking_rules.json",
                "content": _text({section: br[section]}),
            })

    # travel_policies.json — one document per SUB-policy for better RAG chunking.
    # This creates smaller, more focused documents for the vector store, improving
    # the accuracy of similarity searches for specific policy questions.
    tp = _load("travel_policies.json")
    for network_key, network_policies in tp.items():
        if network_key in ("metro", "national_rail"):
            network_name = network_key.replace('_', ' ').title()
            for policy_key, policy_content in network_policies.items():
                policy_name = policy_key.replace('_', ' ').title()
                docs.append({
                    "title": f"Travel Policy: {network_name} — {policy_name}",
                    "category": "conduct",
                    "source_file": "travel_policies.json",
                    "content": _text({policy_key: policy_content}),
                })

    return docs


def seed():
    documents = build_documents()
    print(f"📄 Embedding {len(documents)} policy documents using {llm.chat_provider}...\n")

    for i, doc in enumerate(documents):
        print(f"  [{i+1}/{len(documents)}] Embedding: {doc['title']}")

        try:
            embedding = llm.embed(doc["content"])

            if len(embedding) != llm.embed_dim:
                print(f"    ⚠️  Unexpected embedding dim: {len(embedding)} (expected {llm.embed_dim})")
                print(f"    Update GEMINI_EMBED_DIM or OLLAMA_EMBED_DIM in skeleton/config.py")
                sys.exit(1)

            doc_id = store_policy_document(
                title=doc["title"],
                category=doc["category"],
                content=doc["content"],
                embedding=embedding,
                source_file=doc.get("source_file", ""),
            )
            print(f"    ✓ Stored as document id={doc_id}")

        except Exception as e:
            print(f"    ✗ Failed: {e}")
            raise

        if llm.chat_provider == "gemini" and i < len(documents) - 1:
            time.sleep(0.5)

    print(f"\n✅ All {len(documents)} policy documents embedded and stored.")
    print("   Test with a similarity search:")
    print("   >>> from skeleton.llm_provider import llm")
    print("   >>> from databases.relational.queries import query_policy_vector_search")
    print("   >>> results = query_policy_vector_search(llm.embed('can I get a refund for a delay?'))")
    print("   >>> print(results[0]['title'])")


if __name__ == "__main__":
    seed()
