import { useEffect, useState, type FormEvent } from "react";
import {
  Activity,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Crosshair,
  FileSearch,
  GitCompareArrows,
  LayoutDashboard,
  Network,
  Plus,
  Radio,
  RefreshCw,
  Search,
  ShieldCheck,
  Tags,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { Link, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { CorrelationMap } from "./CorrelationMap";

import {
  createSource,
  updateSource,
  fetchHealth,
  fetchIngestionJobs,
  fetchDocuments,
  fetchDocument,
  classifyDocument,
  prioritizeDocument,
  fetchSources,
  type CTISource,
  type HealthResponse,
  type IngestionJob,
  type CTIDocument,
  type ExtractedEntity,
  type ExtractedEntityDetail,
  fetchEntities,
  fetchEntity,
  fetchAttackObjects,
  fetchDocumentAttackMappings,
  mapDocumentToAttack,
  createCorrelationJob,
  fetchCorrelationJobs,
  fetchLatestCompletedCorrelationJob,
  fetchCorrelations,
  clearCorrelations,
  rerunCorrelationJob,
  fetchCampaigns,
  fetchCampaign,
  runCampaignDiscovery,
  clearCampaignNames,
  decideCampaign,
  type SourceType,
  type AttackObject,
  type AttackMapping,
  type CorrelationJob,
  type CorrelationRecord,
  type Campaign,
  type CampaignDetail,
  fetchGraphStatus,
  searchGraph,
  fetchGraphNeighborhood,
  syncGraphDocument,
  fetchModelStatus,
  type ModelStatus,
  fetchDashboardSummary,
  type DashboardSummary,
} from "./api/client";

const navigation = [
  { label: "Dashboard", to: "/", icon: LayoutDashboard },
  { label: "Sources", to: "/sources", icon: Radio },
  { label: "Ingestion", to: "/ingestion", icon: RefreshCw },
  { label: "Intelligence", to: "/intelligence", icon: FileSearch },
  { label: "Entities", to: "/entities", icon: Tags },
  { label: "ATT&CK", to: "/attack", icon: ShieldCheck },
  { label: "Correlations", to: "/correlations", icon: GitCompareArrows },
  { label: "Correlation Map", to: "/correlation-map", icon: Workflow },
  { label: "Campaigns", to: "/campaigns", icon: Crosshair },
  { label: "Graph", to: "/graph", icon: Network },
  { label: "Model", to: "/model", icon: BrainCircuit },
];

type DashboardData = {
  health: HealthResponse;
  stats: DashboardSummary;
  model: ModelStatus;
  sources: CTISource[];
  documents: CTIDocument[];
  campaigns: Campaign[];
  correlations: CorrelationRecord[];
};

const sourceHealthStatuses: {
  value: CTISource["health_status"];
  label: string;
}[] = [
  { value: "healthy", label: "Healthy" },
  { value: "collecting", label: "Collecting" },
  { value: "unknown", label: "Unknown" },
  { value: "inactive", label: "Inactive" },
  { value: "error", label: "Needs attention" },
];

function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      fetchHealth(),
      fetchDashboardSummary(),
      fetchModelStatus(),
      fetchSources(),
      fetchDocuments({ limit: 5, offset: 0 }),
      fetchCampaigns(),
      fetchCorrelations(),
    ])
      .then(([health, stats, model, sources, documents, campaigns, correlations]) => {
        if (active) setData({ health, stats, model, sources, documents, campaigns, correlations });
      })
      .catch(() => {
        if (active) setError("Unable to load dashboard data. Check API and database connectivity.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const relatedCorrelations = data?.correlations.filter(
    (record) => record.predicted_relationship_label.toLowerCase() === "related",
  ).length ?? 0;
  const otherCorrelations = (data?.correlations.length ?? 0) - relatedCorrelations;
  const recentCorrelations = data
    ? [...data.correlations]
      .sort((first, second) => Date.parse(second.created_at) - Date.parse(first.created_at))
      .slice(0, 3)
    : [];
  const apiAvailable = data?.health.status === "ok";

  return (
    <section className="page-section">
      <div className="dashboard-intro">
        <div>
          <p className="page-eyebrow">Cyber threat intelligence · operations</p>
          <h1 className="dashboard-title">Intelligence overview</h1>
          <p className="dashboard-description">
            A live view of configured collection, campaign activity, and evidence-backed correlation signals.
          </p>
        </div>
        <div className="dashboard-live" role="status">
          <span className={`health-dot ${apiAvailable ? "healthy" : "unknown"}`} />
          {loading ? "Updating" : apiAvailable ? "API connected" : "API unavailable"}
        </div>
      </div>
      {error && <ErrorBanner message={error} />}
      {loading ? (
        <DashboardLoadingState />
      ) : data ? (
        <>
          <div className="metric-grid">
            <MetricCard
              label="API status"
              value={apiAvailable ? "Connected" : "Unavailable"}
              detail="Application service"
              icon={Activity}
            />
            <MetricCard
              label="Configured sources"
              value={String(data.stats.sources)}
              detail={`${data.sources.filter((source) => source.is_active).length} currently active`}
              icon={Radio}
            />
            <MetricCard
              label="Campaigns"
              value={String(data.stats.campaigns)}
              detail="Stored campaign records"
              icon={Crosshair}
            />
            <MetricCard
              label="Correlations"
              value={String(data.stats.correlations)}
              detail="Saved document-pair predictions"
              icon={GitCompareArrows}
            />
            <MetricCard
              label="Predictor"
              value={data.model.is_trained_model
                ? "Trained model"
                : data.model.status === "unavailable"
                  ? "Unavailable"
                  : "Baseline"}
              detail={data.model.error || data.model.model_name || data.model.configured_predictor}
              icon={BrainCircuit}
            />
            <MetricCard
              label="Feature schema"
              value={data.model.feature_schema_version || "Unavailable"}
              detail={`${data.model.input_count ?? 0} model inputs`}
              icon={Workflow}
            />
          </div>

          <div className="dashboard-grid">
            <div className="dashboard-stack">
              <section className="dashboard-panel">
                <PanelHeading
                  title="Recent intelligence"
                  description="Latest normalized reports received by the platform."
                  linkTo="/intelligence"
                  linkLabel="Open intelligence"
                />
                {data.documents.length ? (
                  <div className="document-feed">
                    {data.documents.map((document) => (
                      <Link
                        key={document.id}
                        to="/intelligence"
                        className="document-feed-item"
                      >
                        <span className="document-feed-title">
                          {document.normalized_title || document.title}
                        </span>
                        <span className={`status-${document.normalization_status}`}>
                          {document.normalization_status}
                        </span>
                        <span className="document-feed-meta">
                          <span>{document.document_type}</span>
                          {document.priority_score !== null && (
                            <span>Priority {document.priority_score.toFixed(2)}</span>
                          )}
                        </span>
                        <time className="document-feed-time" dateTime={document.retrieved_at}>
                          {new Date(document.retrieved_at).toLocaleDateString()}
                        </time>
                      </Link>
                    ))}
                  </div>
                ) : (
                  <EmptyState text="No normalized documents are available yet." />
                )}
              </section>

              <section className="dashboard-panel">
                <PanelHeading
                  title="Correlation signal"
                  description="Stored predictions and their relationship labels."
                  linkTo="/correlations"
                  linkLabel="Review correlations"
                />
                {data.correlations.length ? (
                  <>
                    <div
                      className="correlation-split"
                      role="img"
                      aria-label={`${relatedCorrelations} related and ${otherCorrelations} other predictions`}
                    >
                      <span
                        className="correlation-split-related"
                        style={{
                          width: `${(relatedCorrelations / data.correlations.length) * 100}%`,
                        }}
                      />
                      <span
                        className="correlation-split-other"
                        style={{
                          width: `${(otherCorrelations / data.correlations.length) * 100}%`,
                        }}
                      />
                    </div>
                    <div className="correlation-legend">
                      <span><i className="legend-dot" />Related · {relatedCorrelations}</span>
                      <span><i className="legend-dot other" />Other · {otherCorrelations}</span>
                    </div>
                    <div className="correlation-feed">
                      {recentCorrelations.map((record) => (
                        <CorrelationFeedItem key={record.id} record={record} />
                      ))}
                    </div>
                  </>
                ) : (
                  <EmptyState text="No stored correlation predictions are available." />
                )}
              </section>
            </div>

            <div className="dashboard-stack">
              <section className="dashboard-panel">
                <PanelHeading
                  title="Source health"
                  description="Current health reported by configured feeds."
                  linkTo="/sources"
                  linkLabel="Manage sources"
                />
                <SourceHealthBreakdown sources={data.sources} />
              </section>

              <section className="dashboard-panel">
                <PanelHeading
                  title="Campaign activity"
                  description="Most recently updated campaign records."
                  linkTo="/campaigns"
                  linkLabel="Open campaigns"
                />
                {data.campaigns.length ? (
                  <div className="campaign-feed">
                    {data.campaigns.slice(0, 4).map((campaign) => (
                      <div className="campaign-feed-item" key={campaign.id}>
                        <div className="min-w-0">
                          <p className="campaign-feed-name">{campaign.name}</p>
                          <p className="campaign-feed-confidence">
                            {campaign.confidence === null
                              ? "Confidence unavailable"
                              : `${(campaign.confidence * 100).toFixed(0)}% confidence`}
                          </p>
                        </div>
                        <span className={`status-${campaign.status}`}>{campaign.status.replace("_", " ")}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState text="No campaign records are available." />
                )}
              </section>
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}

function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
}) {
  return (
    <article className="metric-card">
      <span className="metric-icon"><Icon size={17} strokeWidth={1.8} /></span>
      <div className="metric-card-copy">
        <p className="metric-label">{label}</p>
        <p className={`metric-value ${value.length > 18 ? "is-text" : ""}`}>{value}</p>
        <p className="metric-detail">{detail}</p>
      </div>
    </article>
  );
}

function StatusCard({
  label,
  value,
  detail,
  icon: Icon = CheckCircle2,
}: {
  label: string;
  value: string;
  detail?: string;
  icon?: LucideIcon;
}) {
  return (
    <div className="status-card">
      <div className="status-card-header">
        <Icon size={15} strokeWidth={1.8} />
        <span className="status-card-label">{label}</span>
      </div>
      <p className="status-card-value">{value}</p>
      {detail && <p className="status-card-detail">{detail}</p>}
    </div>
  );
}

function PanelHeading({
  title,
  description,
  linkTo,
  linkLabel,
}: {
  title: string;
  description: string;
  linkTo?: string;
  linkLabel?: string;
}) {
  return (
    <div className="panel-heading">
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      {linkTo && linkLabel && (
        <Link to={linkTo} className="panel-link">
          {linkLabel}<ChevronRight size={14} />
        </Link>
      )}
    </div>
  );
}

function SourceHealthBreakdown({ sources }: { sources: CTISource[] }) {
  if (!sources.length) return <EmptyState text="No configured sources are available." />;

  return (
    <div className="status-breakdown" aria-label="Source health breakdown">
      {sourceHealthStatuses.map(({ value, label }) => {
        const count = sources.filter((source) => source.health_status === value).length;
        if (!count) return null;
        return (
          <div className="status-breakdown-row" key={value}>
            <div className="status-breakdown-label">
              <span className={`health-dot ${value}`} />
              {label}
            </div>
            <span className="status-breakdown-count">{count}</span>
            <div className="status-track">
              <span
                className={`status-track-fill ${value}`}
                style={{ width: `${(count / sources.length) * 100}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function CorrelationFeedItem({ record }: { record: CorrelationRecord }) {
  const probability = Math.max(0, Math.min(1, record.correlation_probability));
  const isRelated = record.predicted_relationship_label.toLowerCase() === "related";
  return (
    <div className="correlation-feed-item">
      <div className="correlation-feed-top">
        <span>{record.first_document_id.slice(0, 8)} ↔ {record.second_document_id.slice(0, 8)}</span>
        <span className="correlation-feed-score">
          {probability.toFixed(2)} · {record.predicted_relationship_label.replace("_", " ")}
        </span>
      </div>
      <div
        className="probability-track"
        role="progressbar"
        aria-label={`Correlation probability ${probability.toFixed(2)}`}
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuenow={probability}
      >
        <span className="probability-fill" style={{ width: `${probability * 100}%` }} />
        <span
          className="probability-threshold"
          style={{ left: `${record.prediction_threshold * 100}%` }}
          title={`Threshold ${record.prediction_threshold.toFixed(2)}`}
        />
      </div>
      <p className="metric-detail">
        {isRelated ? "Above stored decision threshold" : "Below stored decision threshold"}
      </p>
    </div>
  );
}

function DashboardLoadingState() {
  return (
    <div className="dashboard-stack" role="status" aria-live="polite">
      <span className="sr-only">Loading dashboard data</span>
      <div className="metric-grid">
        {Array.from({ length: 6 }, (_, index) => (
          <div className="metric-card" key={index}>
            <span className="skeleton h-9 w-9" />
            <div className="grid flex-1 gap-2">
              <span className="skeleton h-3 w-24" />
              <span className="skeleton h-5 w-32" />
            </div>
          </div>
        ))}
      </div>
      <div className="dashboard-panel">
        <span className="skeleton block h-4 w-40" />
        <span className="skeleton mt-5 block h-12 w-full" />
        <span className="skeleton mt-3 block h-12 w-full" />
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="dashboard-panel grid gap-3" role="status" aria-live="polite">
      <span className="sr-only">Loading model status</span>
      <span className="skeleton h-4 w-40" />
      <span className="skeleton h-8 w-64" />
      <span className="skeleton h-20 w-full" />
    </div>
  );
}

function ModelPage() {
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { fetchModelStatus().then(setStatus).catch(() => setError("Unable to load model configuration.")); }, []);

  const featureNames = status ? metadataStringArray(status.metadata, "feature_columns") : [];
  const metrics = status ? metadataObject(status.metadata, "evaluation_metrics") : {};
  const modelVersion = status ? metadataString(status.metadata, "model_version") : "Unavailable";

  return (
    <section className="page-section">
      <PageHeading
        eyebrow="Correlation configuration"
        title={status?.model_name || "Model status"}
        description="Live deployment details for the predictor used to score evidence-backed document relationships."
      />
      {error && <ErrorBanner message={error} />}
      {status?.error && <ErrorBanner message={status.error} />}
      {!status && !error && <LoadingState />}
      {status && (
        <>
          <div className="metric-grid">
            <StatusCard
              label="Availability"
              value={status.status}
              detail={status.is_trained_model ? "Artifact loaded successfully" : "Heuristic predictor"}
            />
            <StatusCard
              label="Predictor"
              value={status.configured_predictor}
              detail={status.is_trained_model ? "Trained evidence-aware model" : "Baseline configuration"}
              icon={BrainCircuit}
            />
            <StatusCard
              label="Model inputs"
              value={String(status.input_count ?? "Unavailable")}
              detail="Similarity and report-evidence features"
              icon={Workflow}
            />
            <StatusCard
              label="Decision threshold"
              value={status.threshold.toFixed(2)}
              detail="Stored probability cutoff"
              icon={GitCompareArrows}
            />
            <StatusCard
              label="Model version"
              value={modelVersion}
              detail="Loaded artifact version"
              icon={Radio}
            />
            <StatusCard
              label="Feature schema"
              value={status.feature_schema_version || "Unavailable"}
              detail="Versioned inference contract"
              icon={FileSearch}
            />
          </div>

          <section className="dashboard-panel">
            <PanelHeading
              title="Deployment metadata"
              description="Artifact identity, training reference, and model inputs currently reported by the API."
            />
            <div className="metadata-grid">
              <MetadataItem label="Model type" value={metadataString(status.metadata, "model_type")} />
              <MetadataItem label="Training dataset" value={metadataString(status.metadata, "training_dataset_reference")} />
              <MetadataItem label="Artifact location" value={metadataString(status.metadata, "artifact_location")} />
              <MetadataItem label="Input count" value={`${featureNames.length || status.input_count || 0} features`} />
            </div>
            <details className="technical-details">
              <summary>Technical details and evaluation</summary>
              <h3 className="mt-4 text-sm font-semibold text-slate-300">Model feature order</h3>
              {featureNames.length ? (
                <div className="feature-list">
                  {featureNames.map((name) => <span className="feature-chip" key={name}>{name}</span>)}
                </div>
              ) : (
                <p className="metric-detail">Feature list unavailable.</p>
              )}
              <h3 className="mt-5 text-sm font-semibold text-slate-300">Saved evaluation metrics</h3>
              <div className="metadata-grid mt-3">
                {[
                  ["ROC AUC", metrics.roc_auc],
                  ["PR AUC", metrics.pr_auc],
                  ["F1", metrics.f1],
                  ["Precision", metrics.precision],
                  ["Recall", metrics.recall],
                ].filter((item): item is [string, number] => typeof item[1] === "number" && Number.isFinite(item[1]))
                  .map(([label, value]) => (
                    <MetadataItem key={label} label={label} value={value.toFixed(3)} />
                  ))}
              </div>
            </details>
          </section>
        </>
      )}
    </section>
  );
}

function MetadataItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="metadata-item">
      <p className="metadata-label">{label}</p>
      <p className="metadata-value">{value}</p>
    </div>
  );
}

function metadataString(metadata: Record<string, unknown>, key: string): string {
  const value = metadata[key];
  return typeof value === "string" ? value : "Unavailable";
}

function metadataStringArray(metadata: Record<string, unknown>, key: string): string[] {
  const value = metadata[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function metadataObject(metadata: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = metadata[key];
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function SourcesPage() {
  const [sources, setSources] = useState<CTISource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", source_type: "rss" as SourceType, base_url: "" });
  const [showDisabled, setShowDisabled] = useState(false);
  const [editing, setEditing] = useState<{ id: string; name: string; base_url: string } | null>(null);

  const loadSources = async () => {
    try {
      setSources(await fetchSources());
    } catch {
      setError("Unable to load sources. Check the API and database.");
    }
  };

  useEffect(() => {
    loadSources();
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await createSource({ ...form, configuration: {} });
      setForm({ name: "", source_type: "rss", base_url: "" });
      setError(null);
      await loadSources();
    } catch (err: any) {
      const message =
        err?.response?.data?.detail ||
        err?.message ||
        "Source creation failed. Verify the public URL and API availability.";
      setError(message);
    }
  }

  async function setSourceActive(source: CTISource, is_active: boolean) {
    try {
      await updateSource(source.id, { is_active });
      setError(null);
      await loadSources();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Unable to update source status.");
    }
  }

  async function saveSourceEdit(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    try {
      await updateSource(editing.id, { name: editing.name, base_url: editing.base_url });
      setEditing(null);
      setError(null);
      await loadSources();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Unable to update source.");
    }
  }

  const visibleSources = sources.filter((source) => showDisabled || source.is_active);

  return (
    <section className="page-section">
      <PageHeading eyebrow="Collection control" title="CTI Sources" description="Manage configured CTI feeds and source details." />
      {error && <ErrorBanner message={error} />}
      <form onSubmit={submit} className="grid gap-3 rounded-xl border border-slate-800 bg-panel p-5 md:grid-cols-[1.2fr_1fr_2fr_auto]">
        <input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="Source name" className="field" />
        <select value={form.source_type} onChange={(event) => setForm({ ...form, source_type: event.target.value as SourceType })} className="field">
          <option value="rss">RSS feed</option>
          <option value="nvd">NVD / CVE</option>
          <option value="mitre_attack">MITRE ATT&CK</option>
          <option value="taxii">STIX / TAXII</option>
          <option value="advisory">Security advisory</option>
          <option value="osint">OSINT</option>
          <option value="research">Research</option>
        </select>
        <input required type="url" value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} placeholder="https://public.example/feed" className="field" />
        <button className="button-primary" type="submit"><Plus size={16} /> Add source</button>
      </form>
      <label className="flex items-center gap-2 text-sm text-slate-400">
        <input type="checkbox" checked={showDisabled} onChange={(event) => setShowDisabled(event.target.checked)} />
        Show disabled sources
      </label>
      <div className="space-y-3">
        {visibleSources.map((source) => (
          <div key={source.id} className="source-card flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="flex items-center gap-3">
                <h3 className="font-semibold text-white">{source.name}</h3>
                <span className={`status-${source.health_status}`}>{source.health_status}</span>
                <span className={source.is_active ? "status-healthy" : "status-inactive"}>{source.is_active ? "active" : "disabled"}</span>
              </div>
              <p className="mt-1 text-sm text-slate-400">{typeof source.configuration.demo_category === "string" ? source.configuration.demo_category : source.source_type} · {source.configuration.local_demo_feed === true ? "Fictional local demonstration" : "Configured feed"}</p>
              <p className="mt-1 break-all text-xs text-slate-500">Feed: <a className="text-cyan hover:underline" href={source.base_url} target="_blank" rel="noreferrer">{source.base_url}</a></p>
              {source.configuration.local_demo_feed === true && (
                <p className="mt-1 text-xs"><a className="text-cyan hover:underline" href={source.base_url.replace(/\/feed\.json$/, "/")} target="_blank" rel="noreferrer">Visit publication website</a></p>
              )}
              <p className="mt-2 text-xs text-slate-400">{source.reports_collected} reports · last successful collection: {source.last_successful_collection ? new Date(source.last_successful_collection).toLocaleString() : "never"}</p>
              {editing?.id === source.id && (
                <form onSubmit={saveSourceEdit} className="mt-3 flex flex-wrap gap-2">
                  <input required value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} className="field" aria-label="Source name" />
                  <input required type="url" value={editing.base_url} onChange={(event) => setEditing({ ...editing, base_url: event.target.value })} className="field min-w-80" aria-label="Source feed URL" />
                  <button className="button-primary" type="submit">Save</button>
                  <button className="button-secondary" type="button" onClick={() => setEditing(null)}>Cancel</button>
                </form>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => setEditing({ id: source.id, name: source.name, base_url: source.base_url })} className="button-secondary">Edit</button>
              <button type="button" onClick={() => setSourceActive(source, !source.is_active)} className="button-secondary">{source.is_active ? "Disable" : "Enable"}</button>
            </div>
          </div>
        ))}
        {!visibleSources.length && <EmptyState text={showDisabled ? "No sources configured yet." : "No active sources. Enable one or add a source."} />}
      </div>
    </section>
  );
}

function IngestionPage() {
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const loadJobs = () =>
    fetchIngestionJobs()
      .then(setJobs)
      .catch((err: any) =>
        setError(err?.response?.data?.detail || err?.message || "Unable to load ingestion jobs.")
      ); 
  useEffect(() => {
    loadJobs();
  }, []);

  return (
    <section className="page-section">
      <PageHeading eyebrow="Pipeline monitoring" title="Ingestion jobs" description="Track collection attempts, outcomes, and record counts." />
      {error && <ErrorBanner message={error} />}
      <div className="overflow-hidden rounded-xl border border-slate-800 bg-panel">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
          <span className="text-sm text-slate-400">{jobs.length} jobs</span>
          <button type="button" onClick={loadJobs} className="button-secondary"><RefreshCw size={15} /> Refresh</button>
        </div>
        <div className="divide-y divide-slate-800">
          {jobs.map((job) => (
            <div key={job.id} className="grid gap-2 px-5 py-4 text-sm md:grid-cols-4">
              <span className="font-medium text-white">{job.id.slice(0, 8)}</span>
              <span className={`status-${job.status}`}>{job.status}</span>
              <span className="text-slate-400">{job.records_created} created / {job.records_seen} seen</span>
              <span className="text-slate-500">{job.error_message || new Date(job.created_at).toLocaleString()}</span>
            </div>
          ))}
          {!jobs.length && <EmptyState text="No ingestion jobs recorded yet." />}
        </div>
      </div>
    </section>
  );
}

function IntelligencePage() {
  const [documents, setDocuments] = useState<CTIDocument[]>([]);
  const [selected, setSelected] = useState<CTIDocument | null>(null);
  const [attackMappings, setAttackMappings] = useState<AttackMapping[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  const load = () => fetchDocuments({ limit: 25, offset }).then(setDocuments).catch(() => setError("Unable to load normalized documents."));
  useEffect(() => { load(); }, [offset]);

  async function openDocument(id: string) {
    try {
      setSelected(await fetchDocument(id));
      setAttackMappings(await fetchDocumentAttackMappings(id));
      setError(null);
    } catch {
      setError("Unable to load document details.");
    }

  }

  async function classifySelected() {
    if (!selected) return;
    try {
      setSelected(await classifyDocument(selected.id));
      setError(null);
    } catch {
      setError("Unable to classify document.");
    }
  }

  async function prioritizeSelected() {
    if (!selected) return;
    try {
      setSelected(await prioritizeDocument(selected.id));
      setError(null);
    } catch {
      setError("Unable to prioritize document.");
    }
  }

  async function mapSelectedToAttack() {
    if (!selected) return;
    try {
      setAttackMappings(await mapDocumentToAttack(selected.id));
      setError(null);
    } catch {
      setError("Unable to map document to the official ATT&CK dataset.");
    }
  }

  return (
    <section className="page-section">
      <PageHeading eyebrow="Intelligence explorer" title="Normalized documents" description="Review cleaned CTI content, provenance, and duplicate relationships." />
      {error && <ErrorBanner message={error} />}
      <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
        <div className="overflow-hidden rounded-xl border border-slate-800 bg-panel">
          <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
            <span className="text-sm text-slate-400">{documents.length} documents</span>
            <button type="button" onClick={load} className="button-secondary"><RefreshCw size={15} /> Refresh</button>
          </div>
          <div className="divide-y divide-slate-800">
            {documents.map((document) => (
              <button key={document.id} type="button" onClick={() => openDocument(document.id)} className="document-row w-full px-5 py-4 text-left">
                <div className="flex items-center justify-between gap-3">
                  <span className="truncate font-medium text-white">{document.normalized_title || document.title}</span>
                  <span className={`status-${document.normalization_status}`}>{document.normalization_status}</span>
                </div>
                <p className="mt-1 text-xs text-slate-500">{document.document_type} · {document.content_hash.slice(0, 12)}</p>
              </button>
            ))}
            {!documents.length && <EmptyState text="No normalized documents yet. Run an ingestion job first." />}
          </div>
          <div className="flex justify-between border-t border-slate-800 px-5 py-3"><button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))} className="button-secondary disabled:opacity-40">Previous</button><span className="self-center text-xs text-slate-500">Page {offset / 25 + 1}</span><button type="button" disabled={documents.length < 25} onClick={() => setOffset(offset + 25)} className="button-secondary disabled:opacity-40">Next</button></div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-panel p-6">
          {selected ? (
            <>
              <h3 className="text-xl font-semibold text-white">{selected.original_title}</h3>
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-400">
                <span>{selected.document_type}</span><span>Source: {selected.source_id.slice(0, 8)}</span>
                {selected.duplicate_of_document_id && <span>Duplicate ({selected.duplicate_relationship})</span>}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <button type="button" onClick={classifySelected} className="button-secondary">Classify</button>
                <button type="button" onClick={prioritizeSelected} className="button-secondary">Prioritize</button>
                <button type="button" onClick={mapSelectedToAttack} className="button-secondary">Map ATT&CK</button>
              </div>
              {selected.classification_category && (
                <div className="mt-4 rounded-lg border border-slate-800 p-4 text-sm text-slate-300">
                  <p>Category: <strong className="text-white">{selected.classification_category}</strong> ({selected.classification_confidence?.toFixed(2)})</p>
                  <p className="mt-1 text-xs text-slate-500">Evidence: {String(selected.classification_evidence?.supporting_keywords ?? "none")}</p>
                  {selected.priority_score !== null && <p className="mt-2">Priority: <strong className="text-cyan">{selected.priority_score.toFixed(2)}</strong></p>}
                </div>
              )}
              {attackMappings.length > 0 && (
                <div className="mt-4 rounded-lg border border-slate-800 p-4 text-sm">
                  <p className="font-semibold text-white">ATT&CK mappings</p>
                  <div className="mt-2 space-y-2">
                    {attackMappings.map((mapping) => (
                      <div key={mapping.id} className="text-slate-300">
                        <span className="text-cyan">{mapping.external_id}</span> {mapping.name}
                        <span className="ml-2 text-xs text-slate-500">{mapping.mapping_status} · {mapping.confidence?.toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <a className="mt-4 block truncate text-sm text-cyan hover:underline" href={selected.original_url} target="_blank" rel="noreferrer">{selected.original_url}</a>
              <p className="mt-5 whitespace-pre-wrap text-sm leading-7 text-slate-300">{selected.normalized_text}</p>
              <p className="mt-5 text-xs text-slate-500">Raw record: {selected.raw_record_id || "not available"} · Retrieved {new Date(selected.retrieved_at).toLocaleString()}</p>
            </>
          ) : <p className="text-sm text-slate-500">Select a document to inspect its normalized content and provenance.</p>}
        </div>
      </div>
    </section>
  );
}

function EntitiesPage() {
  const [entities, setEntities] = useState<ExtractedEntity[]>([]);
  const [selected, setSelected] = useState<ExtractedEntityDetail | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => fetchEntities(query.trim() || undefined).then(setEntities).catch(() => setError("Unable to load extracted entities."));
  useEffect(() => { load(); }, []);

  async function openEntity(id: string) {
    try {
      setSelected(await fetchEntity(id));
      setError(null);
    } catch {
      setError("Unable to load entity details.");
    }

  }

  return (
    <section className="page-section">
      <PageHeading eyebrow="Entity explorer" title="Extracted entities" description="Inspect normalized entities, aliases, evidence spans, and document relationships." />
      {error && <ErrorBanner message={error} />}
      <form onSubmit={(event) => { event.preventDefault(); load(); }} className="flex gap-3">
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search entities" className="field flex-1" />
        <button className="button-primary" type="submit"><Search size={16} /> Search</button>
      </form>
      <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
        <div className="overflow-hidden rounded-xl border border-slate-800 bg-panel">
          <div className="border-b border-slate-800 px-5 py-4 text-sm text-slate-400">{entities.length} entities</div>
          <div className="divide-y divide-slate-800">
            {entities.map((entity) => (
              <button key={entity.id} type="button" onClick={() => openEntity(entity.id)} className="document-row w-full px-5 py-4 text-left">
                <p className="font-medium text-white">{entity.canonical_name}</p>
                <p className="mt-1 text-xs text-slate-500">{entity.entity_type} · confidence {entity.confidence?.toFixed(2) ?? "n/a"}</p>
              </button>
            ))}
            {!entities.length && <EmptyState text="No extracted entities yet. Run ingestion on a source first." />}
          </div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-panel p-6">
          {selected ? (
            <>
              <h3 className="text-xl font-semibold text-white">{selected.canonical_name}</h3>
              <p className="mt-2 text-sm text-cyan">{selected.entity_type} · {selected.normalized_value}</p>
              <p className="mt-5 text-sm text-slate-400">Aliases: {String(selected.attributes.aliases ?? "none")}</p>
              <h4 className="mt-6 text-sm font-semibold uppercase tracking-wide text-slate-400">Document evidence</h4>
              <div className="mt-3 space-y-3">
                {selected.document_associations.map((association) => (
                  <div key={association.id} className="rounded-lg border border-slate-800 p-4">
                    <p className="text-sm text-white">{association.mention_text}</p>
                    <p className="mt-2 text-xs leading-5 text-slate-400">{association.evidence_text}</p>
                    <p className="mt-2 text-xs text-slate-500">Document {association.document_id.slice(0, 8)} · {association.extraction_method}</p>
                  </div>
                ))}
                {!selected.document_associations.length && <EmptyState text="No document associations." />}
              </div>
            </>
          ) : <p className="text-sm text-slate-500">Select an entity to inspect evidence and document relationships.</p>}
        </div>
      </div>
    </section>
  );
}

function AttackPage() {
  const [objects, setObjects] = useState<AttackObject[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => fetchAttackObjects(query.trim() || undefined).then(setObjects).catch(() => setError("Unable to load ATT&CK objects. Map a document or run dataset synchronization first."));
  useEffect(() => { load(); }, []);

  return (
    <section className="page-section">
      <PageHeading eyebrow="ATT&CK explorer" title="Enterprise ATT&CK objects" description="Browse versioned techniques, sub-techniques, software, groups, tactics, and references." />
      {error && <ErrorBanner message={error} />}
      <form onSubmit={(event) => { event.preventDefault(); load(); }} className="flex gap-3">
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search techniques, software, or groups" className="field flex-1" />
        <button className="button-primary" type="submit"><Search size={16} /> Search</button>
      </form>
      <div className="space-y-3">
        {objects.map((object) => (
          <div key={object.id} className="rounded-xl border border-slate-800 bg-panel p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="font-semibold text-white">{object.external_id} · {object.name}</h3>
              <span className="status-normalized">{object.object_type}</span>
            </div>
            <p className="mt-2 text-sm text-slate-400">{object.tactic || "No tactic recorded"} · dataset {object.dataset_version || "unknown"}</p>
            {object.aliases.length > 0 && <p className="mt-2 text-xs text-slate-500">Aliases: {object.aliases.join(", ")}</p>}
          </div>
        ))}
        {!objects.length && <EmptyState text="No ATT&CK objects stored yet." />}
      </div>
    </section>
  );
}

const correlationFeatures = [
  ["temporal_similarity", "Temporal"],
  ["entity_relationship_similarity", "Entity relationship"],
  ["behavioural_similarity", "Behavioural"],
  ["attack_technique_similarity", "ATT&CK technique"],
  ["semantic_embedding_similarity", "Semantic embedding"],
  ["knowledge_graph_relationship_similarity", "Knowledge graph"],
] as const;

function CorrelationsPage() {
  const [jobs, setJobs] = useState<CorrelationJob[]>([]);
  const [records, setRecords] = useState<CorrelationRecord[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [threshold, setThreshold] = useState("0.35");
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isClearing, setIsClearing] = useState(false);

  const load = async (jobIdToSelect?: string) => {
    try {
      const jobData = await fetchCorrelationJobs();
      setJobs(jobData);
      const activeJob = jobIdToSelect
        ? jobData.find((j) => j.id === jobIdToSelect) || jobData[0]
        : selectedJobId
          ? jobData.find((j) => j.id === selectedJobId) || jobData[0]
          : jobData[0];

      if (activeJob) {
        setSelectedJobId(activeJob.id);
        const recordData = await fetchCorrelations(undefined, activeJob.id);
        setRecords(recordData);
      } else {
        setSelectedJobId(null);
        setRecords([]);
      }
      setError(null);
    } catch (err: any) {
      const reason = err?.response?.data?.detail || (err instanceof Error ? err.message : "Unable to load correlation jobs or records.");
      setError(reason);
    }
  };

  useEffect(() => { load(); }, []);

  async function run(event: FormEvent) {
    event.preventDefault();
    if (isRunning || isClearing) return;
    const val = Number(threshold);
    if (!Number.isFinite(val) || val < 0 || val > 1) {
      setError("Use a correlation threshold between 0.00 and 1.00.");
      return;
    }

    setIsRunning(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const newJob = await createCorrelationJob({ threshold: val });
      await load(newJob.id);
      setSuccessMessage(`Correlation job ${newJob.id.slice(0, 8)} completed successfully with ${newJob.correlations_created} correlations stored.`);
    } catch (err: any) {
      const reason = err?.response?.data?.detail || (err instanceof Error ? err.message : "Correlation job failed.");
      setError(`Correlation job failed: ${reason}`);
    } finally {
      setIsRunning(false);
    }
  }

  async function rerun(jobId: string) {
    if (isRunning || isClearing) return;
    setIsRunning(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const rerunJob = await rerunCorrelationJob(jobId);
      await load(rerunJob.id);
      setSuccessMessage(`Correlation job ${rerunJob.id.slice(0, 8)} re-run completed with ${rerunJob.correlations_created} correlations stored.`);
    } catch (err: any) {
      const reason = err?.response?.data?.detail || (err instanceof Error ? err.message : "Correlation re-run failed.");
      setError(`Correlation re-run failed: ${reason}`);
    } finally {
      setIsRunning(false);
    }
  }

  async function handleClear() {
    if (isRunning || isClearing) return;
    const confirmed = window.confirm(
      "Are you sure you want to clear all previous correlations? This action removes saved correlation records and job history, but leaves reports, sources, and campaigns intact.",
    );
    if (!confirmed) return;

    setIsClearing(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const result = await clearCorrelations();
      setJobs([]);
      setRecords([]);
      setSelectedJobId(null);
      setSuccessMessage(`Previous correlations cleared (${result.records_cleared} records, ${result.jobs_cleared} jobs).`);
    } catch (err: any) {
      const reason = err?.response?.data?.detail || (err instanceof Error ? err.message : "Failed to clear correlations.");
      setError(`Failed to clear correlations: ${reason}`);
    } finally {
      setIsClearing(false);
    }
  }

  const selectJob = async (id: string) => {
    setSelectedJobId(id);
    try {
      const recordData = await fetchCorrelations(undefined, id);
      setRecords(recordData);
      setError(null);
    } catch (err: any) {
      const reason = err?.response?.data?.detail || (err instanceof Error ? err.message : "Failed to load correlations for job.");
      setError(reason);
    }
  };

  return (
    <section className="page-section">
      <PageHeading eyebrow="Correlation explorer" title="Cross-source relationships" description="Review candidate pairs, all six feature values, probability, evidence, and predictor identity." />
      {error && <ErrorBanner message={error} />}
      {successMessage && (
        <div className="rounded-lg border border-cyan-800/50 bg-cyan-950/40 p-4 text-sm text-cyan flex items-center justify-between">
          <span>{successMessage}</span>
          <button type="button" onClick={() => setSuccessMessage(null)} className="text-xs text-slate-400 hover:text-white">Dismiss</button>
        </div>
      )}
      <form onSubmit={run} className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-800 bg-panel p-5">
        <label className="text-sm text-slate-400 flex items-center gap-2">
          Threshold:
          <input className="field w-28" type="number" min="0" max="1" step="0.01" value={threshold} onChange={(event) => setThreshold(event.target.value)} disabled={isRunning || isClearing} />
        </label>
        <button type="submit" className="button-primary" disabled={isRunning || isClearing}>
          {isRunning ? "Running correlation job..." : "Run correlation job"}
        </button>
        <button type="button" className="button-secondary" onClick={() => load()} disabled={isRunning || isClearing}>
          Refresh
        </button>
        <Link
          to="/correlation-map"
          className="button-secondary flex items-center gap-1.5 text-cyan border-cyan-800/60 hover:bg-cyan-950/30"
        >
          <Workflow size={15} />
          View Correlation Map &rarr;
        </Link>
        <button
          type="button"
          className="button-secondary text-rose-400 border-rose-900/60 hover:bg-rose-950/30 ml-auto"
          onClick={handleClear}
          disabled={isRunning || isClearing}
        >
          {isClearing ? "Clearing..." : "Clear previous correlations"}
        </button>
      </form>
      <div className="rounded-xl border border-slate-800 bg-panel">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4 text-sm text-slate-400">
          <span>Recent jobs ({jobs.length})</span>
          {selectedJobId && <span className="text-xs text-cyan">Active run: {selectedJobId.slice(0, 8)}</span>}
        </div>
        <div className="divide-y divide-slate-800">
          {jobs.map((job) => {
            const isSelected = job.id === selectedJobId;
            return (
              <div
                key={job.id}
                onClick={() => selectJob(job.id)}
                className={`flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-sm cursor-pointer transition-colors ${isSelected ? "bg-slate-800/50 border-l-4 border-l-cyan" : "hover:bg-slate-800/20"}`}
              >
                <div className="flex items-center gap-3">
                  <span className={`font-mono ${isSelected ? "text-cyan font-semibold" : "text-white"}`}>{job.id.slice(0, 8)}</span>
                  <span className={`px-2 py-0.5 rounded text-xs ${job.status === "completed" ? "bg-emerald-950/60 text-emerald-400 border border-emerald-800/40" : job.status === "failed" ? "bg-rose-950/60 text-rose-400 border border-rose-800/40" : "bg-amber-950/60 text-amber-400 border border-amber-800/40"}`}>
                    {job.status}
                  </span>
                </div>
                <span className="text-slate-400">{job.pairs_considered} candidates / {job.correlations_created} stored</span>
                <span className="text-slate-500">{job.predictor_type || "unavailable"} · {job.predictor_version || "n/a"}</span>
                <button
                  type="button"
                  className="button-secondary text-xs py-1 px-3"
                  onClick={(e) => { e.stopPropagation(); rerun(job.id); }}
                  disabled={isRunning || isClearing}
                >
                  Re-run
                </button>
              </div>
            );
          })}
          {!jobs.length && <EmptyState text="No correlation jobs run yet." />}
        </div>
      </div>
      <div className="space-y-4">
        <div className="flex items-center justify-between px-1 text-sm text-slate-400">
          <span>
            {selectedJobId
              ? `Results from run ${selectedJobId.slice(0, 8)} (${records.length} pairs)`
              : `Correlation records (${records.length})`}
          </span>
        </div>
        {records.map((record) => (
          <article key={record.id} className="rounded-xl border border-slate-800 bg-panel p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="font-semibold text-white">{record.first_document_id.slice(0, 8)} vs {record.second_document_id.slice(0, 8)}</p>
              <p className="text-cyan">Probability {record.correlation_probability.toFixed(3)} · {record.predicted_relationship_label}</p>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {correlationFeatures.map(([key, label]) => (
                <div key={key} className="rounded-lg border border-slate-800 px-3 py-2">
                  <p className="text-xs text-slate-500">{label}</p>
                  <p className="mt-1 text-lg text-white">{record[key].toFixed(3)}</p>
                </div>
              ))}
            </div>
            <p className="mt-4 text-xs text-slate-500">Predictor: {record.predictor_type} / {record.predictor_version} · schema {record.feature_schema_version} · threshold {record.prediction_threshold.toFixed(2)}</p>
            <p className="mt-3 text-xs text-amber-300">Candidate correlation only — review the source evidence before treating this relationship as an attribution.</p>
            {!!record.evidence_and_explanation.model_evidence && (
              <pre className="mt-3 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-400">
                {JSON.stringify(record.evidence_and_explanation.model_evidence, null, 2)}
              </pre>
            )}
          </article>
        ))}
        {!records.length && <EmptyState text="No correlation records available for this run." />}
      </div>
    </section>
  );
}

function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [latestJob, setLatestJob] = useState<CorrelationJob | null>(null);
  const [selected, setSelected] = useState<CampaignDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [discoveryMessage, setDiscoveryMessage] = useState<string | null>(null);
  const [clearMessage, setClearMessage] = useState<string | null>(null);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [isClearingNames, setIsClearingNames] = useState(false);
  const [probabilityThreshold, setProbabilityThreshold] = useState("0.35");
  const [minimumSimilarity, setMinimumSimilarity] = useState("0.1");

  async function load() {
    try {
      const job = await fetchLatestCompletedCorrelationJob();
      setLatestJob(job);
      if (job) {
        setCampaigns(await fetchCampaigns(undefined, job.id));
      } else {
        setCampaigns(await fetchCampaigns());
      }
      setError(null);
    } catch (err: any) {
      const reason = err?.response?.data?.detail || (err instanceof Error ? err.message : "Unable to load candidate campaigns.");
      setError(reason);
    }
  }
  useEffect(() => { load(); }, []);

  async function open(id: string) {
    try {
      setSelected(await fetchCampaign(id));
      setError(null);
    } catch {
      setError("Unable to load campaign details.");
    }
  }

  async function decide(decision: "confirmed" | "rejected") {
    if (!selected) return;
    try {
      setSelected(await decideCampaign(selected.id, decision));
      await load();
    } catch {
      setError("Campaign decision could not be saved.");
    }
  }

  async function clearNames() {
    if (isDiscovering || isClearingNames) return;
    const confirmed = window.confirm(
      "Are you sure you want to clear discovered campaign candidate names? This action removes only system-discovered candidate names from the active view, preserving correlations, reports, synthetic demo campaigns, and analyst decisions."
    );
    if (!confirmed) return;

    setIsClearingNames(true);
    setError(null);
    setDiscoveryMessage(null);
    setClearMessage(null);
    try {
      const result = await clearCampaignNames(latestJob?.id);
      await load();
      setSelected(null);
      setClearMessage(`Campaign candidate names cleared (${result.candidates_cleared} candidate group(s) removed).`);
    } catch (err: any) {
      const reason = err?.response?.data?.detail || (err instanceof Error ? err.message : "Failed to clear campaign candidate names.");
      setError(`Failed to clear campaign candidate names: ${reason}`);
    } finally {
      setIsClearingNames(false);
    }
  }

  async function discover() {
    if (isDiscovering || isClearingNames) return;
    if (!latestJob) {
      setError("No completed correlation job found. Run a correlation job on the Correlations page before naming.");
      return;
    }
    const probability = Number(probabilityThreshold);
    const similarity = Number(minimumSimilarity);
    if (
      !Number.isFinite(probability)
      || probability < 0.0
      || probability > 1.0
      || !Number.isFinite(similarity)
      || similarity < 0.0
      || similarity > 1.0
    ) {
      setError("Use a correlation threshold from 0.00 to 1.00 and a feature similarity from 0.00 to 1.00.");
      return;
    }

    setIsDiscovering(true);
    setError(null);
    setDiscoveryMessage(null);
    setClearMessage(null);
    try {
      const discovered = await runCampaignDiscovery({
        probability_threshold: probability,
        minimum_similarity: similarity,
        job_id: latestJob.id,
      });
      setCampaigns((current) => {
        const preserved = current.filter(
          (campaign) =>
            campaign.evidence.classification === "synthetic_demo_ground_truth"
            || campaign.status === "confirmed"
            || campaign.status === "rejected",
        );
        const combined = [...preserved, ...discovered];
        return combined.sort((first, second) =>
          second.updated_at.localeCompare(first.updated_at),
        );
      });
      setSelected(discovered[0] ?? null);
      if (!discovered.length) {
        setDiscoveryMessage(
          `No saved related pairs meet these evidence thresholds for run ${latestJob.id.slice(0, 8)}; no GenAI naming request was made.`,
        );
        return;
      }
      const aiNamed = discovered.filter(
        (campaign) => campaign.evidence.naming?.status === "ai_generated",
      ).length;
      const fallbackNamed = discovered.length - aiNamed;
      setDiscoveryMessage(
        `Processed ${discovered.length} candidate group(s) for run ${latestJob.id.slice(0, 8)}: ${aiNamed} AI-named, ${fallbackNamed} deterministic fallback. Review every candidate before attribution.`,
      );
    } catch (error: any) {
      const reason = error?.response?.data?.detail || (error instanceof Error ? error.message : "Unknown request error.");
      setError(`Campaign discovery request failed: ${reason}`);
    } finally {
      setIsDiscovering(false);
    }
  }

  const selectedIsSynthetic =
    selected?.evidence.classification === "synthetic_demo_ground_truth";
  const naming = selected?.evidence.naming;
  const sharedEntities = selected?.evidence.shared_entities;
  const pairwiseEvidence = selected?.evidence.pairwise_evidence ?? [];
  const sourceNames = selected
    ? [...new Set(
      selected.evidence.source_names
        ?? selected.document_associations.flatMap((association) =>
          association.document?.source?.name
            ? [association.document.source.name]
            : [],
        ),
    )]
    : [];
  const timeline = selected?.evidence.timeline;
  const campaignKind = (campaign: Campaign) => {
    if (campaign.evidence.classification === "synthetic_demo_ground_truth") {
      return "Synthetic demo campaign";
    }
    return campaign.evidence.naming?.status === "ai_generated"
      ? "AI-discovered candidate"
      : "Correlation candidate · fallback name";
  };

  return (
    <section className="page-section">
      <PageHeading eyebrow="Campaign discovery" title="Candidate campaigns" description="Review saved correlation groupings and their evidence-grounded names. Synthetic demo labels are kept separate from discovered candidates." />
      {error && <ErrorBanner message={error} />}
      <div className="rounded-xl border border-slate-800 bg-panel p-4">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
          <div className="max-w-2xl">
            <p className="text-sm font-semibold text-white">Run evidence-grounded campaign naming</p>
            <p className="mt-1 text-xs leading-5 text-slate-400">
              Uses correlations from the latest completed correlation run only; it does not rerun or change predictions.
              Demonstration thresholds are relaxed, so every result remains a provisional candidate.
              Eligible report excerpts are sent to the configured GenAI provider.
            </p>
            {latestJob ? (
              <div className="mt-2 flex items-center gap-2 text-xs text-slate-300">
                <span className="inline-block h-2 w-2 rounded-full bg-emerald-400" />
                <span>
                  Target correlation run: <strong className="font-mono text-cyan">{latestJob.id.slice(0, 8)}</strong>
                  {" "}(completed {new Date(latestJob.completed_at || latestJob.requested_at).toLocaleTimeString()})
                </span>
              </div>
            ) : (
              <div className="mt-2 flex items-center gap-2 text-xs text-amber-400">
                <span className="inline-block h-2 w-2 rounded-full bg-amber-400" />
                <span>No completed correlation run found. Run a correlation job on the Correlations page before naming.</span>
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs text-slate-400">
              Correlation threshold
              <input
                className="field mt-1 w-32"
                type="number"
                min="0"
                max="1"
                step="0.01"
                value={probabilityThreshold}
                onChange={(event) => setProbabilityThreshold(event.target.value)}
                aria-label="Campaign correlation threshold"
              />
            </label>
            <label className="text-xs text-slate-400">
              Feature similarity
              <input
                className="field mt-1 w-32"
                type="number"
                min="0"
                max="1"
                step="0.01"
                value={minimumSimilarity}
                onChange={(event) => setMinimumSimilarity(event.target.value)}
                aria-label="Minimum supporting feature similarity"
              />
            </label>
            <button
              type="button"
              className="button-primary"
              onClick={discover}
              disabled={isDiscovering || isClearingNames || !latestJob}
              title={!latestJob ? "Run a correlation job first" : undefined}
            >
              <BrainCircuit size={15} />
              {isDiscovering ? "Naming in progress..." : "Run naming"}
            </button>
            <button
              type="button"
              className="button-secondary"
              onClick={clearNames}
              disabled={isDiscovering || isClearingNames || !latestJob}
            >
              {isClearingNames ? "Clearing names..." : "Clear campaign names"}
            </button>
            <button type="button" className="button-secondary" onClick={load} disabled={isDiscovering || isClearingNames}>Refresh</button>
          </div>
        </div>
        {discoveryMessage && (
          <p className="mt-3 text-sm text-cyan" role="status">{discoveryMessage}</p>
        )}
        {clearMessage && (
          <p className="mt-3 text-sm text-amber-300" role="status">{clearMessage}</p>
        )}
      </div>
      <div className="grid gap-6 lg:grid-cols-[1fr_1.5fr]">
        <div className="overflow-hidden rounded-xl border border-slate-800 bg-panel">
          <div className="border-b border-slate-800 px-5 py-4 text-sm text-slate-400">{campaigns.length} campaigns</div>
          <div className="divide-y divide-slate-800">
            {campaigns.map((campaign) => {
              const reportCount =
                campaign.evidence.supporting_report_ids?.length
                ?? campaign.evidence.member_count;
              return (
                <button key={campaign.id} type="button" onClick={() => open(campaign.id)} className="document-row w-full px-5 py-4 text-left">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <span className="font-medium text-white">{campaign.name}</span>
                    <span className={`status-${campaign.status}`}>{campaign.status}</span>
                  </div>
                  <span className="mt-2 inline-flex rounded-full border border-slate-700 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-300">
                    {campaignKind(campaign)}
                  </span>
                  <p className="mt-2 text-xs text-slate-500">
                    {reportCount === undefined ? "" : `${reportCount} reports · `}
                    {campaign.confidence?.toFixed(2) ?? "n/a"} correlation confidence
                  </p>
                  {campaign.evidence.source_names?.length ? (
                    <p className="mt-1 break-words text-xs text-slate-500">
                      {campaign.evidence.source_names.join(" · ")}
                    </p>
                  ) : null}
                </button>
              );
            })}
            {!campaigns.some((c) => c.evidence.classification === "correlation_discovered_candidate" && c.status === "candidate") && (
              <div className="p-5 text-center text-xs text-slate-500">
                {latestJob
                  ? `Correlation run ${latestJob.id.slice(0, 8)} has not yet been named. Click "Run naming" to discover candidate campaigns.`
                  : "No candidate campaigns discovered yet."}
              </div>
            )}
            {!campaigns.length && <EmptyState text="No campaigns available." />}
          </div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-panel p-6">
          {selected ? (
            <>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-xl font-semibold text-white">{selected.name}</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-400">{selected.description}</p>
                  <span className="mt-3 inline-flex rounded-full border border-slate-700 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-300">
                    {selectedIsSynthetic ? "Synthetic demo campaign" : campaignKind(selected)}
                  </span>
                </div>
                <div className="flex gap-2">
                  <button type="button" className="button-secondary" onClick={() => decide("confirmed")}>Confirm</button>
                  <button type="button" className="button-secondary" onClick={() => decide("rejected")}>Reject</button>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm">
                <p className="text-cyan">Correlation confidence: {selected.confidence?.toFixed(3) ?? "n/a"}</p>
                <p className="text-slate-400">Verification: {selectedIsSynthetic ? "Synthetic validation label" : selected.status}</p>
                <p className="text-slate-400">Reports: {selected.document_associations.length}</p>
                <p className="text-slate-400">
                  Naming: {selectedIsSynthetic
                    ? "Ground truth only · not a model prediction"
                    : naming?.status === "ai_generated"
                      ? `AI-generated · ${naming.model ?? "model not reported"}`
                      : "Deterministic fallback · analyst review required"}
                </p>
              </div>
              {selected.evidence.discovery_thresholds && (
                <p className="mt-2 text-xs text-amber-300">
                  {selected.evidence.discovery_thresholds.profile === "demonstration_relaxed"
                    ? "Demonstration thresholds"
                    : "Standard thresholds"}
                  {" · "}correlation ≥ {selected.evidence.discovery_thresholds.probability_threshold.toFixed(2)}
                  {" · "}supporting similarity ≥ {selected.evidence.discovery_thresholds.minimum_similarity.toFixed(2)}
                  {" · provisional; analyst review required"}
                </p>
              )}
              {naming?.fallback_reason ? (
                <p className="mt-2 text-xs text-amber-300">
                  GenAI fallback: {naming.fallback_reason}
                </p>
              ) : null}

              <h4 className="mt-6 text-sm font-semibold uppercase tracking-wide text-slate-400">
                Supporting sources
              </h4>
              <p className="mt-2 break-words text-sm text-slate-300">
                {sourceNames.length ? sourceNames.join(" · ") : "No source metadata available."}
              </p>

              <h4 className="mt-6 text-sm font-semibold uppercase tracking-wide text-slate-400">
                Shared threat evidence
              </h4>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {(["actors", "malware", "tools", "techniques", "indicators"] as const).map((category) => (
                  <div key={category} className="min-w-0 rounded-lg border border-slate-800 p-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      {category}
                    </p>
                    <p className="mt-2 break-words text-sm text-slate-200">
                      {sharedEntities?.[category]?.length
                        ? sharedEntities[category].join(", ")
                        : "No shared evidence recorded"}
                    </p>
                  </div>
                ))}
              </div>

              <h4 className="mt-6 text-sm font-semibold uppercase tracking-wide text-slate-400">
                Supporting reports
              </h4>
              <div className="mt-3 space-y-2">
                {selected.document_associations.map((association) => (
                  <div key={association.id} className="min-w-0 rounded-lg border border-slate-800 p-3 text-sm">
                    <p className="break-words font-medium text-white">
                      {association.document?.original_title || association.document?.title || "Untitled report"}
                    </p>
                    <p className="mt-1 break-words text-xs text-slate-400">
                      {association.document?.source?.name ?? "Unknown source"}
                      {association.document?.published_at
                        ? ` · ${new Date(association.document.published_at).toLocaleDateString()}`
                        : ""}
                    </p>
                    {association.document?.original_url ? (
                      <a
                        className="mt-1 block break-all text-xs text-cyan hover:underline"
                        href={association.document.original_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {association.document.original_url}
                      </a>
                    ) : null}
                    <p className="mt-2 break-all font-mono text-[10px] text-slate-500">
                      {association.document_id}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      {association.association_type} · {association.relevance_score?.toFixed(3) ?? "n/a"} score
                    </p>
                  </div>
                ))}
              </div>

              {!selectedIsSynthetic ? (
                <>
                  <h4 className="mt-6 text-sm font-semibold uppercase tracking-wide text-slate-400">
                    Why these reports were grouped
                  </h4>
                  {naming?.activity_summary?.text ? (
                    <p className="mt-2 text-sm leading-6 text-slate-300">
                      {naming.activity_summary.text}
                    </p>
                  ) : null}
                  {naming?.grouping_rationale?.text ? (
                    <p className="mt-2 text-sm leading-6 text-slate-400">
                      {naming.grouping_rationale.text}
                    </p>
                  ) : null}
                  {naming?.main_supporting_evidence?.length ? (
                    <ul className="mt-3 space-y-2">
                      {naming.main_supporting_evidence.map((item, index) => (
                        <li key={`${index}-${item.evidence_ids.join("-")}`} className="rounded-lg border border-slate-800 p-3">
                          <p className="text-sm text-slate-300">{item.text}</p>
                          <p className="mt-2 break-all font-mono text-[10px] text-slate-500">
                            Evidence: {item.evidence_ids.join(", ")}
                          </p>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {naming?.contradictions_or_limitations?.length ? (
                    <div className="mt-3 rounded-lg border border-amber-900/60 bg-amber-500/5 p-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-amber-300">
                        Limitations / contradictory evidence
                      </p>
                      {naming.contradictions_or_limitations.map((item, index) => (
                        <p key={`${index}-${item.evidence_ids.join("-")}`} className="mt-2 text-sm text-slate-300">
                          {item.text}
                        </p>
                      ))}
                    </div>
                  ) : null}

                  <h4 className="mt-6 text-sm font-semibold uppercase tracking-wide text-slate-400">
                    Saved correlation evidence
                  </h4>
                  <div className="mt-3 space-y-2">
                    {pairwiseEvidence.map((item) => (
                      <div key={item.correlation_id} className="min-w-0 rounded-lg border border-slate-800 p-3">
                        <div className="flex flex-wrap justify-between gap-2 text-sm">
                          <span className="text-white">
                            {item.report_ids.map((id) => id.slice(0, 8)).join(" ↔ ")}
                          </span>
                          <span className="text-cyan">
                            {(item.probability * 100).toFixed(1)}% · {item.label}
                          </span>
                        </div>
                        <p className="mt-1 break-words text-xs text-slate-400">
                          {item.predictor ?? "Unknown predictor"} · {item.predictor_version ?? "version unavailable"}
                        </p>
                        <p className="mt-1 break-words text-xs text-slate-500">
                          Supporting dimensions: {item.supporting_dimensions.join(", ") || "none"}
                        </p>
                      </div>
                    ))}
                    {!pairwiseEvidence.length ? (
                      <p className="text-sm text-slate-500">No pairwise correlation details are attached.</p>
                    ) : null}
                  </div>
                </>
              ) : null}

              <h4 className="mt-6 text-sm font-semibold uppercase tracking-wide text-slate-400">Timeline</h4>
              {timeline?.start || timeline?.end ? (
                <p className="mt-2 text-xs text-slate-400">
                  Published: {timeline.start ? new Date(timeline.start).toLocaleString() : "unknown"}
                  {" — "}
                  {timeline.end ? new Date(timeline.end).toLocaleString() : "unknown"}
                </p>
              ) : null}
              <div className="mt-3 space-y-2">
                {selected.history.map((event) => (
                  <div key={event.id} className="border-l border-cyan/40 pl-3 text-xs">
                    <p className="text-slate-300">{event.event_type} · {event.new_status || "recorded"}</p>
                    <p className="text-slate-500">{new Date(event.occurred_at).toLocaleString()} {event.comments || ""}</p>
                  </div>
                ))}
              </div>
            </>
          ) : <p className="text-sm text-slate-500">Select a campaign to inspect evidence and history.</p>}
        </div>
      </div>
    </section>
  );
}

function GraphPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Record<string, unknown>[]>([]);
  const [status, setStatus] = useState<string>("Checking...");
  const [selected, setSelected] = useState<Record<string, unknown>[]>([]);
  const [selectedNode, setSelectedNode] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchGraphStatus()
      .then((response) => setStatus(`${response.status} · ${response.database}`))
      .catch(() => setStatus("unavailable"));
  }, []);

  async function search(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    try {
      setResults(await searchGraph(query.trim()));
      setError(null);
    } catch {
      setError("Neo4j is unavailable. Start the graph service and retry.");
    }
  }

  async function openNode(node: Record<string, unknown>) {
    const stableId = typeof node.stable_id === "string" ? node.stable_id : null;
    if (!stableId) return;
    try {
      setSelectedNode(node);
      setSelected(await fetchGraphNeighborhood(stableId));
      setError(null);
    } catch {
      setError("Unable to load graph relationships.");
    }
  }

  async function syncSelected() {
    const stableId = typeof selectedNode?.stable_id === "string" ? selectedNode.stable_id : null;
    const documentId = stableId?.startsWith("ThreatReport:") ? stableId.slice("ThreatReport:".length) : null;
    if (!documentId) {
      setError("Select a ThreatReport result before synchronizing.");
      return;
    }
    try {
      await syncGraphDocument(documentId);
      setError(null);
    } catch {
      setError("Graph synchronization failed; the retry state was recorded.");
    }
  }

  return (
    <section className="page-section">
      <PageHeading eyebrow="Knowledge graph" title="Graph explorer" description="Search predefined Neo4j views of reports, sources, entities, campaigns, vulnerabilities, and ATT&CK techniques." />
      {error && <ErrorBanner message={error} />}
      <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-panel p-5 text-sm">
        <span className="text-slate-400">Neo4j status</span>
        <span className={status.startsWith("connected") ? "text-emerald-300" : "text-amber-300"}>{status}</span>
      </div>
      <form onSubmit={search} className="flex gap-3">
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search graph node names" className="field flex-1" />
        <button type="submit" className="button-primary"><Search size={15} /> Search</button>
        <button type="button" className="button-secondary" onClick={syncSelected}>Sync report</button>
      </form>
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-panel">
          <h3 className="border-b border-slate-800 px-5 py-4 font-semibold text-white">Nodes</h3>
          <div className="divide-y divide-slate-800">
            {results.map((result, index) => {
              const node = (result.node || result) as Record<string, unknown>;
              return <button key={`${String(node.stable_id)}-${index}`} type="button" onClick={() => openNode(node)} className="document-row w-full px-5 py-4 text-left">
                <p className="font-medium text-white">{String(node.name || node.stable_id || "Unnamed node")}</p>
                <p className="mt-1 text-xs text-slate-500">{String(node.stable_id || "")}</p>
              </button>;
            })}
            {!results.length && <EmptyState text="Search for a graph node to begin." />}
          </div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-panel">
          <h3 className="border-b border-slate-800 px-5 py-4 font-semibold text-white">Relationships</h3>
          <div className="divide-y divide-slate-800">
            {selected.map((item, index) => <pre key={index} className="overflow-auto px-5 py-4 text-xs text-slate-400">{JSON.stringify(item, null, 2)}</pre>)}
            {!selected.length && <EmptyState text="Select a node to inspect its evidence-backed relationships." />}
          </div>
        </div>
      </div>
    </section>
  );
}

function PageHeading({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return (
    <header className="page-heading">
      <div className="page-heading-copy">
        <p className="page-eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
    </header>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="error-banner" role="alert">
      <CircleAlert size={16} aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="empty-state">{text}</div>;
}

export default function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand" aria-label="CyberMind home">
            <span className="brand-mark"><ShieldCheck size={21} strokeWidth={1.8} /></span>
            <span>
              <span className="brand-name">CYBERMIND</span>
              <span className="brand-caption">THREAT INTELLIGENCE</span>
            </span>
          </Link>
          <div className="topbar-meta">
            <span className="environment-label">
              <span className="environment-dot" />
              DEMONSTRATION
            </span>
            <span className="environment-state">
              <Activity size={14} aria-hidden="true" />
              Evidence-aware platform
            </span>
          </div>
        </div>
      </header>
      <div className="app-frame">
        <aside className="sidebar">
          <p className="sidebar-label">Workspace</p>
          <nav className="sidebar-nav" aria-label="Primary navigation">
            {navigation.map(({ label, to, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  `nav-link ${isActive ? "is-active" : ""}`
                }
              >
                <Icon size={17} strokeWidth={1.8} aria-hidden="true" />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-footer">
            <span className="sidebar-footer-icon"><Activity size={15} /></span>
            <span>
              <span className="sidebar-footer-title">Analyst workspace</span>
              <span className="sidebar-footer-caption">Threat research console</span>
            </span>
          </div>
        </aside>
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/sources" element={<SourcesPage />} />
            <Route path="/ingestion" element={<IngestionPage />} />
            <Route path="/intelligence" element={<IntelligencePage />} />
            <Route path="/entities" element={<EntitiesPage />} />
            <Route path="/attack" element={<AttackPage />} />
            <Route path="/correlations" element={<CorrelationsPage />} />
            <Route path="/correlation-map" element={<CorrelationMap />} />
            <Route path="/campaigns" element={<CampaignsPage />} />
            <Route path="/graph" element={<GraphPage />} />
            <Route path="/model" element={<ModelPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
