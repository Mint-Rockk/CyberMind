# GenAI Threat Investigation

CyberMind uses a provider-independent `LLMProvider` contract. The initial adapter
supports OpenAI-compatible chat-completion APIs through `httpx`; no provider SDK
or key is hardcoded.

Set `GENAI_PROVIDER=disabled` to keep the feature unavailable, or configure:

```dotenv
GENAI_PROVIDER=openai_compatible
GENAI_API_KEY=replace-with-provider-key
GENAI_BASE_URL=https://api.openai.com/v1
GENAI_MODEL=gpt-4o-mini
GENAI_TIMEOUT=30
```

Retrieved CTI is explicitly delimited as untrusted data and cannot supply
instructions. Provider output must be JSON, and every factual statement must
cite an evidence ID returned by the hybrid RAG service. Confirmed facts,
inferences, interpretations, recommendations, and intelligence gaps are stored
separately. Correlation values, campaign labels, and analyst decisions are
read-only inputs.

Investigation records retain the original query, retrieval context, evidence
references, structured output, provider metadata, completion time, and failure
details. A configured provider failure is surfaced; the system never silently
falls back to a baseline or invents an answer.

## Threat intelligence assistant

The assistant API stores bounded conversation history in
`assistant_conversations` and `assistant_messages`. Each turn performs the same
hybrid RAG retrieval across Qdrant, PostgreSQL, Neo4j, correlations, campaigns,
and ATT&CK mappings. Only predefined, parameterized service methods are used;
the API accepts no SQL, Cypher, or shell input. Conversation history is context
only, while current factual claims must cite evidence from the current retrieval.

Use `POST /api/v1/assistant/conversations` to start a conversation,
`POST /api/v1/assistant/conversations/{id}/messages` to ask a question, and the
corresponding GET endpoints to list conversations and messages.
