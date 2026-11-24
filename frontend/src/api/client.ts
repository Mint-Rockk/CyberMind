import axios from "axios";

export const apiClient = axios.create({
  baseURL: "/api/v1",
  timeout: 120_000,
});

export type HealthResponse = {
  status: string;
  service: string;
  timestamp: string;
};

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await apiClient.get<HealthResponse>("/health");
  return response.data;
}

export type ModelStatus = {
  status: "available" | "unavailable";
  configured_predictor: string;
  is_trained_model: boolean;
  model_name: string | null;
  input_count: number | null;
  metadata: Record<string, unknown>;
  feature_schema_version: string | null;
  threshold: number;
  error?: string;
};

export async function fetchModelStatus(): Promise<ModelStatus> {
  return (await apiClient.get<ModelStatus>("/model/status")).data;
}

export type DashboardSummary = {
  sources: number;
  campaigns: number;
  correlations: number;
};

export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  return (await apiClient.get<DashboardSummary>("/dashboard/summary")).data;
}

export type SourceType = "rss" | "advisory" | "nvd" | "mitre_attack" | "taxii" | "osint" | "research";

export type CTISource = {
  id: string;
  name: string;
  source_type: SourceType;
  base_url: string;
  reliability_score: number | null;
  is_active: boolean;
  terms_url: string | null;
  configuration: Record<string, unknown>;
  health_status: "healthy" | "unknown" | "inactive" | "collecting" | "error";
  last_successful_collection: string | null;
  reports_collected: number;
  created_at: string;
};

export type IngestionJob = {
  id: string;
  source_id: string;
  status: "pending" | "running" | "completed" | "failed";
  records_seen: number;
  records_created: number;
  error_message: string | null;
  created_at: string;
};

export async function fetchSources(): Promise<CTISource[]> {
  return (await apiClient.get<CTISource[]>("/sources")).data;
}

export async function createSource(input: {
  name: string;
  source_type: SourceType;
  base_url: string;
  configuration: Record<string, unknown>;
}): Promise<CTISource> {
  return (await apiClient.post<CTISource>("/sources", input)).data;
}

export async function updateSource(
  id: string,
  input: Partial<Pick<CTISource, "name" | "base_url" | "source_type" | "is_active">>,
) {
  return (await apiClient.put<CTISource>(`/sources/${id}`, input)).data;
}

export async function fetchIngestionJobs(): Promise<IngestionJob[]> {
  return (await apiClient.get<IngestionJob[]>("/ingestion/jobs")).data;
}

export type CTIDocument = {
  id: string;
  source_id: string;
  raw_record_id: string | null;
  canonical_key: string;
  title: string;
  normalized_content: string;
  original_title: string;
  normalized_title: string;
  normalized_text: string;
  original_url: string;
  content_hash: string;
  document_type: string;
  normalization_status: "pending" | "normalized" | "duplicate" | "failed";
  duplicate_of_document_id: string | null;
  duplicate_relationship: string | null;
  document_status: "ingested" | "normalized" | "reviewed";
  published_at: string | null;
  retrieved_at: string;
  provenance: Record<string, unknown>;
  information_confidence: number | null;
  classification_category: string | null;
  classification_confidence: number | null;
  classification_method: string | null;
  classification_evidence: Record<string, unknown> | null;
  classified_at: string | null;
  priority_score: number | null;
  priority_factors: Record<string, unknown> | null;
  priority_method: string | null;
  prioritized_at: string | null;
  created_at: string;
};

export async function fetchDocuments(input?: { limit?: number; offset?: number; document_type?: string }): Promise<CTIDocument[]> {
  return (await apiClient.get<CTIDocument[]>("/documents", { params: input })).data;
}

export async function fetchDocument(id: string): Promise<CTIDocument> {
  return (await apiClient.get<CTIDocument>(`/documents/${id}`)).data;
}

export async function classifyDocument(id: string): Promise<CTIDocument> {
  return (await apiClient.post<CTIDocument>(`/documents/${id}/classify`)).data;
}

export async function prioritizeDocument(id: string): Promise<CTIDocument> {
  return (await apiClient.post<CTIDocument>(`/documents/${id}/prioritize`)).data;
}

export type EntityType =
  | "threat_actor" | "apt_group" | "malware" | "ransomware" | "tool"
  | "ip_address" | "domain" | "url" | "file_hash" | "cve"
  | "vulnerability" | "campaign" | "sector" | "attack_reference";

export type EntityAssociation = {
  id: string;
  document_id: string;
  entity_id: string;
  mention_text: string | null;
  evidence_text: string | null;
  evidence_start: number | null;
  evidence_end: number | null;
  extraction_method: string | null;
  confidence: number | null;
  extracted_at: string;
};

export type ExtractedEntity = {
  id: string;
  entity_type: EntityType;
  canonical_name: string;
  normalized_value: string;
  confidence: number | null;
  attributes: Record<string, unknown>;
  created_at: string;
};

export type ExtractedEntityDetail = ExtractedEntity & {
  document_associations: EntityAssociation[];
};

export async function fetchEntities(search?: string): Promise<ExtractedEntity[]> {
  return (await apiClient.get<ExtractedEntity[]>("/entities", { params: search ? { search } : undefined })).data;
}

export async function fetchEntity(id: string): Promise<ExtractedEntityDetail> {
  return (await apiClient.get<ExtractedEntityDetail>(`/entities/${id}`)).data;
}

export type AttackObject = {
  id: string;
  external_id: string;
  name: string;
  object_type: string;
  tactic: string | null;
  version: string | null;
  description: string | null;
  aliases: string[];
  external_references: Record<string, unknown>[];
  dataset_version: string | null;
  created_at: string;
};

export async function fetchAttackObjects(search?: string): Promise<AttackObject[]> {
  return (await apiClient.get<AttackObject[]>("/attack/techniques", { params: search ? { search } : undefined })).data;
}

export type AttackMapping = {
  id: string;
  document_id: string;
  technique_id: string;
  external_id: string;
  name: string;
  object_type: string;
  tactic: string | null;
  confidence: number | null;
  evidence: string | null;
  mapping_method: string | null;
  mapping_status: string;
  dataset_version: string | null;
};

export async function fetchDocumentAttackMappings(documentId: string): Promise<AttackMapping[]> {
  return (await apiClient.get<AttackMapping[]>(`/attack/documents/${documentId}/mappings`)).data;
}

export async function mapDocumentToAttack(documentId: string): Promise<AttackMapping[]> {
  return (await apiClient.post<{ mappings: AttackMapping[] }>(`/attack/documents/${documentId}/map`)).data.mappings;
}

export type CorrelationJob = {
  id: string;
  status: "pending" | "running" | "completed" | "failed";
  threshold: number;
  document_id: string | null;
  campaign_id: string | null;
  rerun: boolean;
  pairs_considered: number;
  correlations_created: number;
  predictor_type: string | null;
  predictor_version: string | null;
  error_message: string | null;
  requested_at: string;
  completed_at: string | null;
};

export type CorrelationRecord = {
  id: string;
  first_document_id: string;
  second_document_id: string;
  temporal_similarity: number;
  entity_relationship_similarity: number;
  behavioural_similarity: number;
  attack_technique_similarity: number;
  semantic_embedding_similarity: number;
  knowledge_graph_relationship_similarity: number;
  correlation_probability: number;
  prediction_threshold: number;
  predicted_relationship_label: string;
  predictor_type: string;
  predictor_version: string;
  feature_schema_version: string;
  evidence_and_explanation: Record<string, unknown>;
  created_at: string;
};

export async function createCorrelationJob(input: { threshold: number }): Promise<CorrelationJob> {
  return (
    await apiClient.post<CorrelationJob>("/correlations/jobs", input, {
      timeout: 120_000,
    })
  ).data;
}

export async function fetchCorrelationJobs(): Promise<CorrelationJob[]> {
  return (await apiClient.get<CorrelationJob[]>("/correlations/jobs")).data;
}

export async function fetchLatestCompletedCorrelationJob(): Promise<CorrelationJob | null> {
  return (await apiClient.get<CorrelationJob | null>("/correlations/jobs/latest-completed")).data;
}

export async function rerunCorrelationJob(id: string): Promise<CorrelationJob> {
  return (
    await apiClient.post<CorrelationJob>(`/correlations/jobs/${id}/rerun`, undefined, {
      timeout: 120_000,
    })
  ).data;
}

export async function fetchCorrelations(minProbability?: number, jobId?: string): Promise<CorrelationRecord[]> {
  const params: Record<string, unknown> = {};
  if (minProbability !== undefined) params.min_probability = minProbability;
  if (jobId !== undefined) params.job_id = jobId;
  return (
    await apiClient.get<CorrelationRecord[]>("/correlations", {
      params: Object.keys(params).length ? params : undefined,
      timeout: 30_000,
    })
  ).data;
}

export async function clearCorrelations(): Promise<{ status: string; records_cleared: number; jobs_cleared: number }> {
  return (
    await apiClient.delete<{ status: string; records_cleared: number; jobs_cleared: number }>("/correlations", {
      timeout: 60_000,
    })
  ).data;
}

export type CorrelationGraphNode = {
  id: string;
  type: "report" | "entity";
  label: string;
  source_id: string | null;
  source_name: string | null;
  published_at: string | null;
  entity_type: string | null;
  canonical_name: string | null;
  attributes: Record<string, unknown>;
};

export type CorrelationGraphEdge = {
  id: string;
  source: string;
  target: string;
  type: "correlation" | "has_entity";
  label: string;
  probability: number | null;
  prediction_threshold: number | null;
  is_related: boolean | null;
  predictor_type: string | null;
  predictor_version: string | null;
  feature_similarities: Record<string, number>;
  evidence: Record<string, unknown>;
};

export type CorrelationGraphSummary = {
  job_id: string | null;
  job_status: string | null;
  requested_at: string | null;
  completed_at: string | null;
  threshold: number | null;
  pairs_considered: number;
  correlations_created: number;
  related_count: number;
  unrelated_count: number;
  report_count: number;
  entity_count: number;
  predictor_type: string | null;
  predictor_version: string | null;
};

export type CorrelationGraphResponse = {
  job: CorrelationJob | null;
  summary: CorrelationGraphSummary;
  nodes: CorrelationGraphNode[];
  edges: CorrelationGraphEdge[];
};

export async function fetchLatestCompletedCorrelationGraph(
  onlyRelated = false,
  includeEntities = true,
  minProbability?: number,
): Promise<CorrelationGraphResponse> {
  const params: Record<string, unknown> = {
    only_related: onlyRelated,
    include_entities: includeEntities,
  };
  if (minProbability !== undefined) params.min_probability = minProbability;
  return (
    await apiClient.get<CorrelationGraphResponse>("/correlations/jobs/latest-completed/graph", {
      params,
      timeout: 60_000,
    })
  ).data;
}

export async function fetchCorrelationJobGraph(
  jobId: string,
  onlyRelated = false,
  includeEntities = true,
  minProbability?: number,
): Promise<CorrelationGraphResponse> {
  const params: Record<string, unknown> = {
    only_related: onlyRelated,
    include_entities: includeEntities,
  };
  if (minProbability !== undefined) params.min_probability = minProbability;
  return (
    await apiClient.get<CorrelationGraphResponse>(`/correlations/jobs/${jobId}/graph`, {
      params,
      timeout: 60_000,
    })
  ).data;
}

export type CampaignAssociation = {
  id: string;
  campaign_id: string;
  document_id: string;
  relevance_score: number | null;
  association_reason: string | null;
  association_type: string;
  association_evidence: Record<string, unknown>;
  document: CampaignReportSummary | null;
};

export type CampaignReportSummary = {
  id: string;
  title: string;
  original_title: string;
  original_url: string;
  published_at: string | null;
  source: {
    name: string;
    base_url: string;
  } | null;
};

export type CampaignEvidenceStatement = {
  text: string;
  evidence_ids: string[];
};

export type CampaignSharedEntities = {
  actors: string[];
  malware: string[];
  tools: string[];
  techniques: string[];
  indicators: string[];
};

export type CampaignNaming = {
  status: "ai_generated" | "fallback" | string;
  provider: string | null;
  model: string | null;
  is_official_name: boolean;
  analyst_review_required: boolean;
  fallback_reason?: string;
  activity_summary?: CampaignEvidenceStatement;
  main_supporting_evidence?: CampaignEvidenceStatement[];
  grouping_rationale?: CampaignEvidenceStatement;
  shared_entities?: CampaignSharedEntities;
  supporting_source_names?: string[];
  supporting_report_ids?: string[];
  contradictions_or_limitations?: CampaignEvidenceStatement[];
};

export type CampaignPairwiseEvidence = {
  correlation_id: string;
  report_ids: string[];
  probability: number;
  label: string;
  predictor: string | null;
  predictor_version: string | null;
  supporting_dimensions: string[];
  features: Record<string, { available: boolean | null; score: number | null }>;
  shared_entities: CampaignSharedEntities;
};

export type CampaignEvidence = Record<string, unknown> & {
  classification?: string;
  discovery_thresholds?: {
    probability_threshold: number;
    minimum_similarity: number;
    profile: "demonstration_relaxed" | "standard";
  };
  source_names?: string[];
  supporting_report_ids?: string[];
  member_count?: number;
  shared_entities?: CampaignSharedEntities;
  pairwise_evidence?: CampaignPairwiseEvidence[];
  timeline?: { start: string | null; end: string | null };
  naming?: CampaignNaming;
};

export type CampaignHistory = {
  id: string;
  campaign_id: string;
  event_type: string;
  previous_status: string | null;
  new_status: string | null;
  actor_id: string | null;
  comments: string | null;
  event_evidence: Record<string, unknown>;
  occurred_at: string;
};

export type Campaign = {
  id: string;
  name: string;
  status: "candidate" | "under_review" | "confirmed" | "rejected";
  description: string | null;
  confidence: number | null;
  evidence: CampaignEvidence;
  created_at: string;
  updated_at: string;
};

export type CampaignDetail = Campaign & {
  document_associations: CampaignAssociation[];
  history: CampaignHistory[];
};

export type CampaignDiscoveryRequest = {
  probability_threshold: number;
  minimum_similarity: number;
  job_id?: string;
};

export async function fetchCampaigns(status?: string, jobId?: string, allRuns?: boolean): Promise<Campaign[]> {
  const params: Record<string, unknown> = {};
  if (status !== undefined) params.status = status;
  if (jobId !== undefined) params.job_id = jobId;
  if (allRuns !== undefined) params.all_runs = allRuns;
  return (
    await apiClient.get<Campaign[]>("/campaigns", {
      params: Object.keys(params).length ? params : undefined,
    })
  ).data;
}

export async function clearCampaignNames(
  jobId?: string,
): Promise<{ status: string; candidates_cleared: number; job_id?: string }> {
  const params: Record<string, unknown> = {};
  if (jobId !== undefined) params.job_id = jobId;
  return (
    await apiClient.delete<{ status: string; candidates_cleared: number; job_id?: string }>("/campaigns", {
      params: Object.keys(params).length ? params : undefined,
      timeout: 60_000,
    })
  ).data;
}

export async function runCampaignDiscovery(
  request: CampaignDiscoveryRequest,
): Promise<CampaignDetail[]> {
  return (
    await apiClient.post<CampaignDetail[]>("/campaigns/discover", request, {
      timeout: 240_000,
    })
  ).data;
}

export async function fetchCampaign(id: string): Promise<CampaignDetail> {
  return (await apiClient.get<CampaignDetail>(`/campaigns/${id}`)).data;
}

export async function decideCampaign(
  id: string,
  decision: "confirmed" | "rejected",
  relationshipOrigin: "analyst_confirmed" | "source_confirmed" = "analyst_confirmed",
): Promise<CampaignDetail> {
  return (await apiClient.post<CampaignDetail>(`/campaigns/${id}/decision`, {
    decision,
    relationship_origin: relationshipOrigin,
  })).data;
}

export type GraphStatus = {
  status: string;
  database: string;
};

export async function fetchGraphStatus(): Promise<GraphStatus> {
  return (await apiClient.get<GraphStatus>("/graph/status")).data;
}

export async function searchGraph(query: string, label?: string): Promise<Record<string, unknown>[]> {
  return (await apiClient.get<Record<string, unknown>[]>("/graph/search", {
    params: { query, ...(label ? { label } : {}) },
  })).data;
}

export async function fetchGraphNeighborhood(stableNodeId: string): Promise<Record<string, unknown>[]> {
  return (await apiClient.get<Record<string, unknown>[]>(
    `/graph/neighborhood/${encodeURIComponent(stableNodeId)}`,
  )).data;
}

export async function syncGraphDocument(documentId: string): Promise<{
  resource_id: string;
  nodes_written: number;
  relationships_written: number;
  attempts: number;
}> {
  return (await apiClient.post(`/graph/sync/documents/${documentId}`)).data;
}

