import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  CircleAlert,
  ExternalLink,
  FileText,
  Filter,
  Info,
  Layers,
  List,
  Maximize2,
  Network,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Tag,
  Workflow,
  X,
  XCircle,
  ZoomIn,
  ZoomOut,
} from "lucide-react";

import {
  fetchLatestCompletedCorrelationGraph,
  type CorrelationGraphEdge,
  type CorrelationGraphNode,
  type CorrelationGraphResponse,
} from "./api/client";

// Visual color tokens for entity categories
const ENTITY_COLORS: Record<string, { bg: string; border: string; text: string; label: string }> = {
  threat_actor: { bg: "rgba(245, 158, 11, 0.15)", border: "#f59e0b", text: "#fbbf24", label: "Threat Actor" },
  apt_group: { bg: "rgba(245, 158, 11, 0.15)", border: "#f59e0b", text: "#fbbf24", label: "Threat Actor" },
  actor: { bg: "rgba(245, 158, 11, 0.15)", border: "#f59e0b", text: "#fbbf24", label: "Threat Actor" },
  malware: { bg: "rgba(244, 63, 94, 0.15)", border: "#f43f5e", text: "#fb7185", label: "Malware" },
  ransomware: { bg: "rgba(225, 29, 72, 0.2)", border: "#e11d48", text: "#fda4af", label: "Ransomware" },
  tool: { bg: "rgba(168, 85, 247, 0.15)", border: "#a855f7", text: "#c084fc", label: "Tool" },
  ip_address: { bg: "rgba(16, 185, 129, 0.15)", border: "#10b981", text: "#34d399", label: "IP Address" },
  domain: { bg: "rgba(20, 184, 166, 0.15)", border: "#14b8a6", text: "#2dd4bf", label: "Domain" },
  url: { bg: "rgba(6, 182, 212, 0.15)", border: "#06b6d4", text: "#22d3ee", label: "URL" },
  file_hash: { bg: "rgba(99, 102, 241, 0.15)", border: "#6366f1", text: "#818cf8", label: "Hash" },
  cve: { bg: "rgba(249, 115, 22, 0.15)", border: "#f97316", text: "#fb923c", label: "CVE" },
  vulnerability: { bg: "rgba(249, 115, 22, 0.15)", border: "#f97316", text: "#fb923c", label: "Vulnerability" },
};

function getEntityStyle(type?: string | null) {
  const key = (type || "").toLowerCase();
  return (
    ENTITY_COLORS[key] || {
      bg: "rgba(148, 163, 184, 0.12)",
      border: "#94a3b8",
      text: "#cbd5e1",
      label: type || "Entity",
    }
  );
}

// Compute deterministic layout for nodes in a clean cluster space
function computeInitialLayout(
  nodes: CorrelationGraphNode[],
  edges: CorrelationGraphEdge[],
  width: number,
  height: number,
): Record<string, { x: number; y: number }> {
  const positions: Record<string, { x: number; y: number }> = {};
  if (!nodes.length) return positions;

  const reportNodes = nodes.filter((n) => n.type === "report");
  const entityNodes = nodes.filter((n) => n.type === "entity");

  // Build adjacency for reports connected by "related" correlations
  const relatedAdj: Record<string, Set<string>> = {};
  reportNodes.forEach((n) => {
    relatedAdj[n.id] = new Set();
  });
  edges
    .filter((e) => e.type === "correlation" && e.is_related)
    .forEach((e) => {
      if (relatedAdj[e.source] && relatedAdj[e.target]) {
        relatedAdj[e.source].add(e.target);
        relatedAdj[e.target].add(e.source);
      }
    });

  // Identify connected report clusters
  const visited = new Set<string>();
  const clusters: string[][] = [];

  for (const r of reportNodes) {
    if (!visited.has(r.id)) {
      const cluster: string[] = [];
      const queue = [r.id];
      visited.add(r.id);
      while (queue.length > 0) {
        const curr = queue.shift()!;
        cluster.push(curr);
        for (const neighbor of relatedAdj[curr] || []) {
          if (!visited.has(neighbor)) {
            visited.add(neighbor);
            queue.push(neighbor);
          }
        }
      }
      clusters.push(cluster);
    }
  }

  // Sort clusters descending by size
  clusters.sort((a, b) => b.length - a.length);

  const centerX = width / 2;
  const centerY = height / 2;
  const numClusters = clusters.length;

  clusters.forEach((cluster, clusterIdx) => {
    // Cluster center angle & radius
    const clusterAngle = (clusterIdx / Math.max(1, numClusters)) * 2 * Math.PI;
    const clusterDist = numClusters <= 1 ? 0 : Math.min(width, height) * 0.32;
    const cX = centerX + (clusterDist ? Math.cos(clusterAngle) * clusterDist : 0);
    const cY = centerY + (clusterDist ? Math.sin(clusterAngle) * clusterDist : 0);

    const clusterRadius = Math.max(70, Math.min(220, cluster.length * 28));

    cluster.forEach((reportId, idx) => {
      if (cluster.length === 1) {
        positions[reportId] = { x: cX, y: cY };
      } else {
        const angle = (idx / cluster.length) * 2 * Math.PI;
        positions[reportId] = {
          x: cX + Math.cos(angle) * clusterRadius,
          y: cY + Math.sin(angle) * clusterRadius,
        };
      }
    });
  });

  // Position entity nodes orbiting their associated reports
  const entityReportMap: Record<string, string[]> = {};
  edges
    .filter((e) => e.type === "has_entity")
    .forEach((e) => {
      if (!entityReportMap[e.target]) entityReportMap[e.target] = [];
      entityReportMap[e.target].push(e.source);
    });

  entityNodes.forEach((entity, idx) => {
    const connectedReports = entityReportMap[entity.id] || [];
    if (connectedReports.length > 0) {
      // Position at centroid of connected reports with small jitter
      let sumX = 0;
      let sumY = 0;
      let count = 0;
      connectedReports.forEach((repId) => {
        if (positions[repId]) {
          sumX += positions[repId].x;
          sumY += positions[repId].y;
          count++;
        }
      });
      if (count > 0) {
        const angle = ((idx % 8) / 8) * 2 * Math.PI;
        const jitterDist = 45;
        positions[entity.id] = {
          x: sumX / count + Math.cos(angle) * jitterDist,
          y: sumY / count + Math.sin(angle) * jitterDist,
        };
      } else {
        const angle = (idx / entityNodes.length) * 2 * Math.PI;
        positions[entity.id] = {
          x: centerX + Math.cos(angle) * (Math.min(width, height) * 0.42),
          y: centerY + Math.sin(angle) * (Math.min(width, height) * 0.42),
        };
      }
    } else {
      const angle = (idx / entityNodes.length) * 2 * Math.PI;
      positions[entity.id] = {
        x: centerX + Math.cos(angle) * (Math.min(width, height) * 0.44),
        y: centerY + Math.sin(angle) * (Math.min(width, height) * 0.44),
      };
    }
  });

  return positions;
}

export function CorrelationMap() {
  const [data, setData] = useState<CorrelationGraphResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters & Controls
  const [onlyRelated, setOnlyRelated] = useState(true);
  const [showEntities, setShowEntities] = useState(true);
  const [minProbability, setMinProbability] = useState(0.35);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedSource, setSelectedSource] = useState<string>("all");
  const [showLegend, setShowLegend] = useState(true);
  const [viewMode, setViewMode] = useState<"graph" | "table">("graph");
  const [tableTab, setTableTab] = useState<"correlations" | "reports" | "entities">("correlations");

  // Selection & Interactivity
  const [selectedNode, setSelectedNode] = useState<CorrelationGraphNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<CorrelationGraphEdge | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  // Zoom & Pan state
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  // Node Dragging state
  const [draggedNodeId, setDraggedNodeId] = useState<string | null>(null);
  const [nodePositions, setNodePositions] = useState<Record<string, { x: number; y: number }>>({});

  const svgRef = useRef<SVGSVGElement | null>(null);
  const CANVAS_WIDTH = 1400;
  const CANVAS_HEIGHT = 900;

  const loadGraph = async () => {
    setIsLoading(true);
    setError(null);
    try {
      // Fetch full graph without backend restriction, allowing rich frontend toggling
      const res = await fetchLatestCompletedCorrelationGraph(false, true);
      setData(res);

      // Compute initial layout
      if (res.nodes.length > 0) {
        const layout = computeInitialLayout(res.nodes, res.edges, CANVAS_WIDTH, CANVAS_HEIGHT);
        setNodePositions(layout);
      }
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || "Failed to load correlation graph.";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadGraph();
  }, []);

  // Filtered nodes and edges based on user settings
  const filteredData = useMemo(() => {
    if (!data) return { nodes: [], edges: [], reportCount: 0, entityCount: 0 };

    const q = searchQuery.trim().toLowerCase();

    // Filter nodes
    const nodes = data.nodes.filter((node) => {
      if (!showEntities && node.type === "entity") return false;
      if (selectedSource !== "all" && node.type === "report" && node.source_name !== selectedSource) {
        return false;
      }
      if (q) {
        const label = (node.label || "").toLowerCase();
        const source = (node.source_name || "").toLowerCase();
        const type = (node.entity_type || "").toLowerCase();
        return label.includes(q) || source.includes(q) || type.includes(q);
      }
      return true;
    });

    const nodeIds = new Set(nodes.map((n) => n.id));

    // Filter edges
    const edges = data.edges.filter((edge) => {
      // Both endpoints must exist in visible nodes
      if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) return false;

      if (edge.type === "correlation") {
        if (onlyRelated && !edge.is_related) return false;
        if (edge.probability !== null && edge.probability < minProbability) return false;
      } else if (edge.type === "has_entity") {
        if (!showEntities) return false;
      }
      return true;
    });

    const reportCount = nodes.filter((n) => n.type === "report").length;
    const entityCount = nodes.filter((n) => n.type === "entity").length;

    return { nodes, edges, reportCount, entityCount };
  }, [data, onlyRelated, showEntities, minProbability, searchQuery, selectedSource]);

  // Unique sources list for filter
  const sourcesList = useMemo(() => {
    if (!data) return [];
    const set = new Set<string>();
    data.nodes.forEach((n) => {
      if (n.type === "report" && n.source_name) set.add(n.source_name);
    });
    return Array.from(set).sort();
  }, [data]);

  // Connected nodes for hover highlight
  const highlightNeighborIds = useMemo(() => {
    if (!hoveredNodeId && !selectedNode) return null;
    const targetId = hoveredNodeId || selectedNode?.id;
    if (!targetId || !data) return null;
    const connected = new Set<string>([targetId]);
    data.edges.forEach((e) => {
      if (e.source === targetId) connected.add(e.target);
      if (e.target === targetId) connected.add(e.source);
    });
    return connected;
  }, [hoveredNodeId, selectedNode, data]);

  // Handlers for Canvas Pan & Zoom
  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    setZoom((prev) => Math.min(3.5, Math.max(0.3, prev * factor)));
  };

  const handleMouseDownCanvas = (e: React.MouseEvent) => {
    if (e.button !== 0 || draggedNodeId) return;
    setIsPanning(true);
    setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isPanning) {
      setPan({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y });
    } else if (draggedNodeId) {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return;
      // Convert screen coordinates to canvas space
      const mouseX = (e.clientX - rect.left - pan.x) / zoom;
      const mouseY = (e.clientY - rect.top - pan.y) / zoom;
      setNodePositions((prev) => ({
        ...prev,
        [draggedNodeId]: { x: mouseX, y: mouseY },
      }));
    }
  };

  const handleMouseUp = () => {
    setIsPanning(false);
    setDraggedNodeId(null);
  };

  const resetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

  const fitToView = () => {
    if (!filteredData.nodes.length) {
      resetView();
      return;
    }
    let minX = Infinity,
      maxX = -Infinity,
      minY = Infinity,
      maxY = -Infinity;
    filteredData.nodes.forEach((n) => {
      const p = nodePositions[n.id];
      if (p) {
        minX = Math.min(minX, p.x);
        maxX = Math.max(maxX, p.x);
        minY = Math.min(minY, p.y);
        maxY = Math.max(maxY, p.y);
      }
    });
    const padding = 100;
    const graphWidth = maxX - minX + padding * 2;
    const graphHeight = maxY - minY + padding * 2;
    const scaleX = CANVAS_WIDTH / graphWidth;
    const scaleY = CANVAS_HEIGHT / graphHeight;
    const newZoom = Math.min(2.0, Math.max(0.4, Math.min(scaleX, scaleY)));
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    setZoom(newZoom);
    setPan({
      x: CANVAS_WIDTH / 2 - centerX * newZoom,
      y: CANVAS_HEIGHT / 2 - centerY * newZoom,
    });
  };

  const nodesById = useMemo(() => {
    if (!data) return {};
    const map: Record<string, CorrelationGraphNode> = {};
    data.nodes.forEach((n) => {
      map[n.id] = n;
    });
    return map;
  }, [data]);

  return (
    <section className="page-section">
      {/* Header */}
      <header className="page-heading">
        <div className="page-heading-copy">
          <p className="page-eyebrow">Demonstration Explorer</p>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-white sm:text-3xl">Correlation Map</h1>
            <span className="rounded-full border border-cyan-800/60 bg-cyan-950/50 px-2.5 py-0.5 text-xs font-semibold text-cyan">
              Latest Run Visualizer
            </span>
          </div>
          <p className="text-slate-400">
            Visual inspection of cross-source report relationships, feature similarities, and extracted threat entities
            from the most recent <strong className="text-slate-200">Run correlation job</strong>.
          </p>
        </div>
      </header>

      {error && (
        <div className="error-banner" role="alert">
          <CircleAlert size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* Active Run Banner */}
      <div className="rounded-xl border border-slate-800 bg-panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-3">
            {data?.job ? (
              <>
                <span className="flex items-center gap-1.5 rounded-full border border-emerald-800/60 bg-emerald-950/60 px-3 py-1 text-xs font-medium text-emerald-300">
                  <CheckCircle2 size={13} />
                  Status: Completed
                </span>
                <span className="text-sm font-medium text-slate-300">
                  Run ID: <code className="rounded bg-slate-900 px-1.5 py-0.5 text-cyan">{data.job.id.slice(0, 8)}</code>
                </span>
                {data.job.completed_at && (
                  <span className="text-xs text-slate-400">
                    Finished: {new Date(data.job.completed_at).toLocaleTimeString()} (
                    {new Date(data.job.completed_at).toLocaleDateString()})
                  </span>
                )}
              </>
            ) : isLoading ? (
              <span className="text-sm text-slate-400">Checking latest correlation run...</span>
            ) : (
              <span className="flex items-center gap-1.5 rounded-full border border-amber-800/60 bg-amber-950/60 px-3 py-1 text-xs font-medium text-amber-300">
                <CircleAlert size={13} />
                No Completed Correlation Job Found
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={loadGraph}
              disabled={isLoading}
              className="button-secondary flex items-center gap-1.5 text-xs"
              title="Refresh graph from saved results without rerunning ML job"
            >
              <RefreshCw size={13} className={isLoading ? "animate-spin" : ""} />
              Refresh Map
            </button>
            <Link
              to="/correlations"
              className="rounded-lg border border-cyan-800/50 bg-cyan-950/40 px-3 py-1.5 text-xs font-medium text-cyan hover:bg-cyan-900/40"
            >
              Run new job &rarr;
            </Link>
          </div>
        </div>

        {data?.summary && data.job && (
          <div className="mt-4 grid grid-cols-2 gap-3 border-t border-slate-800 pt-4 sm:grid-cols-4 lg:grid-cols-6">
            <div className="rounded-lg bg-slate-900/60 p-2.5">
              <span className="text-xs text-slate-500">Reports Evaluated</span>
              <p className="text-lg font-semibold text-white">{data.summary.report_count}</p>
            </div>
            <div className="rounded-lg bg-slate-900/60 p-2.5">
              <span className="text-xs text-slate-500">Related Pairs</span>
              <p className="text-lg font-semibold text-cyan">{data.summary.related_count}</p>
            </div>
            <div className="rounded-lg bg-slate-900/60 p-2.5">
              <span className="text-xs text-slate-500">Below Threshold</span>
              <p className="text-lg font-semibold text-slate-400">{data.summary.unrelated_count}</p>
            </div>
            <div className="rounded-lg bg-slate-900/60 p-2.5">
              <span className="text-xs text-slate-500">Extracted Entities</span>
              <p className="text-lg font-semibold text-amber-400">{data.summary.entity_count}</p>
            </div>
            <div className="rounded-lg bg-slate-900/60 p-2.5">
              <span className="text-xs text-slate-500">Decision Threshold</span>
              <p className="text-lg font-semibold text-slate-200">{data.summary.threshold?.toFixed(2) ?? "0.35"}</p>
            </div>
            <div className="rounded-lg bg-slate-900/60 p-2.5">
              <span className="text-xs text-slate-500">Predictor</span>
              <p className="truncate text-xs font-medium text-slate-300" title={data.summary.predictor_type || ""}>
                {data.summary.predictor_type ? "Random Forest" : "Evidence RF"}
              </p>
              <span className="text-[10px] text-slate-500">{data.summary.predictor_version || "v3"}</span>
            </div>
          </div>
        )}
      </div>

      {/* Explanatory Legend / Teacher's Guide */}
      <div className="rounded-xl border border-slate-800 bg-panel">
        <button
          type="button"
          onClick={() => setShowLegend(!showLegend)}
          className="flex w-full items-center justify-between px-5 py-3.5 text-left text-sm font-semibold text-slate-200 hover:text-white"
        >
          <div className="flex items-center gap-2">
            <Info size={16} className="text-cyan" />
            <span>Demonstration Guide: How to Interpret this Graph</span>
          </div>
          {showLegend ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>

        {showLegend && (
          <div className="border-t border-slate-800 px-5 py-4 text-xs leading-relaxed text-slate-300">
            <div className="grid gap-4 md:grid-cols-3">
              <div>
                <h4 className="font-semibold text-white mb-1.5 flex items-center gap-1.5">
                  <span className="h-3 w-3 rounded-full border-2 border-cyan bg-slate-900" />
                  Report Nodes (Cyan Outlined)
                </h4>
                <p className="text-slate-400">
                  Each circle represents a single CTI advisory or incident report ingested from a security source (e.g.,
                  CyberWatch, MalwareScope). Hover or click to read its full title and source.
                </p>
              </div>

              <div>
                <h4 className="font-semibold text-white mb-1.5 flex items-center gap-1.5">
                  <span className="h-3 w-3 rotate-45 border border-amber-400 bg-amber-950/60" />
                  Entity Nodes (Color-Coded Diamonds)
                </h4>
                <p className="text-slate-400">
                  Extracted threat indicators directly referenced in report bodies:
                  <span className="ml-1 text-amber-300">Threat Actors</span>,
                  <span className="ml-1 text-rose-300">Malware</span>,
                  <span className="ml-1 text-purple-300">Tools</span>,
                  <span className="ml-1 text-emerald-300">IPs/URLs</span>.
                </p>
              </div>

              <div>
                <h4 className="font-semibold text-white mb-1.5 flex items-center gap-1.5">
                  <span className="h-0.5 w-4 bg-cyan" />
                  Relationship Lines (Edges)
                </h4>
                <p className="text-slate-400">
                  <strong className="text-cyan">Solid Cyan:</strong> Predicted correlation (<code className="text-cyan">related</code>, P &ge; 0.35) evaluated across all 6 features.
                  <br />
                  <strong className="text-slate-400">Dashed Slate:</strong> Below-threshold evaluated pair.
                  <br />
                  <strong className="text-slate-400">Dotted Gray:</strong> Stored entity mention in a report.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Filter and View Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-panel p-4 text-xs">
        <div className="flex flex-wrap items-center gap-3">
          {/* View mode toggle */}
          <div className="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-0.5">
            <button
              type="button"
              onClick={() => setViewMode("graph")}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition ${
                viewMode === "graph" ? "bg-cyan text-slate-950 shadow" : "text-slate-400 hover:text-white"
              }`}
            >
              <Network size={13} />
              Interactive Map
            </button>
            <button
              type="button"
              onClick={() => setViewMode("table")}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition ${
                viewMode === "table" ? "bg-cyan text-slate-950 shadow" : "text-slate-400 hover:text-white"
              }`}
            >
              <List size={13} />
              Accessible Table
            </button>
          </div>

          {/* Toggle: Only related */}
          <label className="flex cursor-pointer select-none items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-1.5 text-slate-300 hover:border-slate-700">
            <input
              type="checkbox"
              checked={onlyRelated}
              onChange={(e) => setOnlyRelated(e.target.checked)}
              className="accent-cyan"
            />
            <span>Show Related Only</span>
          </label>

          {/* Toggle: Show entities */}
          <label className="flex cursor-pointer select-none items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-1.5 text-slate-300 hover:border-slate-700">
            <input
              type="checkbox"
              checked={showEntities}
              onChange={(e) => setShowEntities(e.target.checked)}
              className="accent-cyan"
            />
            <span>Show Entities</span>
          </label>

          {/* Source Dropdown */}
          {sourcesList.length > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-slate-500">Source:</span>
              <select
                value={selectedSource}
                onChange={(e) => setSelectedSource(e.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 outline-none focus:border-cyan"
              >
                <option value="all">All Sources ({sourcesList.length})</option>
                {sourcesList.map((src) => (
                  <option key={src} value={src}>
                    {src}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Probability threshold slider */}
          <div className="flex items-center gap-2">
            <span className="text-slate-500">Min Prob:</span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={minProbability}
              onChange={(e) => setMinProbability(parseFloat(e.target.value))}
              className="w-20 accent-cyan"
            />
            <span className="font-mono text-cyan">{minProbability.toFixed(2)}</span>
          </div>
        </div>

        {/* Search Input */}
        <div className="relative min-w-[200px] flex-1 max-w-xs">
          <Search size={13} className="absolute left-2.5 top-2.5 text-slate-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search report or entity..."
            className="w-full rounded-lg border border-slate-700 bg-slate-900 py-1.5 pl-8 pr-3 text-xs text-slate-200 outline-none focus:border-cyan"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="absolute right-2 top-2 text-slate-500 hover:text-white"
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      {/* Main View Area */}
      {viewMode === "graph" ? (
        <div className="relative flex min-h-[650px] overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
          {/* Canvas Zoom/Pan Controls */}
          <div className="absolute left-4 top-4 z-10 flex flex-col gap-1.5 rounded-lg border border-slate-800 bg-slate-900/90 p-1.5 shadow-lg backdrop-blur">
            <button
              type="button"
              onClick={() => setZoom((prev) => Math.min(3.5, prev * 1.2))}
              className="rounded p-1 text-slate-300 hover:bg-slate-800 hover:text-white"
              title="Zoom In"
            >
              <ZoomIn size={16} />
            </button>
            <button
              type="button"
              onClick={() => setZoom((prev) => Math.max(0.3, prev * 0.8))}
              className="rounded p-1 text-slate-300 hover:bg-slate-800 hover:text-white"
              title="Zoom Out"
            >
              <ZoomOut size={16} />
            </button>
            <button
              type="button"
              onClick={fitToView}
              className="rounded p-1 text-slate-300 hover:bg-slate-800 hover:text-white"
              title="Fit to View"
            >
              <Maximize2 size={16} />
            </button>
            <button
              type="button"
              onClick={resetView}
              className="rounded p-1 text-slate-300 hover:bg-slate-800 hover:text-white"
              title="Reset View"
            >
              <RefreshCw size={14} />
            </button>
          </div>

          {/* Visibility Counter */}
          <div className="absolute bottom-4 left-4 z-10 rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-1.5 text-xs text-slate-400 backdrop-blur">
            Showing <strong className="text-cyan">{filteredData.reportCount}</strong> reports,{" "}
            <strong className="text-amber-400">{filteredData.entityCount}</strong> entities,{" "}
            <strong className="text-white">{filteredData.edges.length}</strong> links
          </div>

          {/* SVG Graph Canvas */}
          <div
            className="flex-1 cursor-grab active:cursor-grabbing overflow-hidden"
            onMouseDown={handleMouseDownCanvas}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onWheel={handleWheel}
          >
            {filteredData.nodes.length === 0 ? (
              <div className="flex h-full min-h-[500px] flex-col items-center justify-center p-8 text-center text-slate-400">
                <Network size={40} className="mb-3 text-slate-600" />
                <p className="text-base font-semibold text-slate-300">No nodes match the selected filters</p>
                <p className="mt-1 text-xs text-slate-500 max-w-sm">
                  Try unchecking &ldquo;Show Related Only&rdquo;, adjusting the probability slider, or clearing the search query.
                </p>
              </div>
            ) : (
              <svg
                ref={svgRef}
                viewBox={`0 0 ${CANVAS_WIDTH} ${CANVAS_HEIGHT}`}
                className="h-full w-full select-none"
                style={{ width: "100%", height: "650px" }}
              >
                <defs>
                  {/* Glowing filter for selected elements */}
                  <filter id="glow-cyan" x="-20%" y="-20%" width="140%" height="140%">
                    <feGaussianBlur stdDeviation="4" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                  </filter>
                </defs>

                <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
                  {/* Edges Layer */}
                  {filteredData.edges.map((edge) => {
                    const sourcePos = nodePositions[edge.source];
                    const targetPos = nodePositions[edge.target];
                    if (!sourcePos || !targetPos) return null;

                    const isSelected = selectedEdge?.id === edge.id;
                    const isCorrelation = edge.type === "correlation";
                    const isRelated = edge.is_related === true;

                    // Compute edge appearance
                    let strokeColor = "#475569";
                    let strokeWidth = 1.2;
                    let strokeDasharray = undefined;
                    let opacity = 0.4;

                    if (isCorrelation) {
                      if (isRelated) {
                        strokeColor = isSelected ? "#38bdf8" : "#06b6d4";
                        const prob = edge.probability ?? 0.5;
                        strokeWidth = Math.max(1.8, Math.min(5.0, prob * 5));
                        opacity = isSelected ? 1.0 : 0.75;
                      } else {
                        strokeColor = isSelected ? "#94a3b8" : "#334155";
                        strokeDasharray = "4 4";
                        strokeWidth = 1.2;
                        opacity = isSelected ? 0.9 : 0.3;
                      }
                    } else {
                      // Report to Entity
                      strokeColor = "#64748b";
                      strokeDasharray = "2 3";
                      strokeWidth = 1.0;
                      opacity = 0.35;
                    }

                    // Midpoint for label
                    const midX = (sourcePos.x + targetPos.x) / 2;
                    const midY = (sourcePos.y + targetPos.y) / 2;

                    return (
                      <g
                        key={edge.id}
                        className="cursor-pointer group"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedEdge(edge);
                          setSelectedNode(null);
                        }}
                      >
                        {/* Invisible thick path for easier clicking */}
                        <line
                          x1={sourcePos.x}
                          y1={sourcePos.y}
                          x2={targetPos.x}
                          y2={targetPos.y}
                          stroke="transparent"
                          strokeWidth={14}
                        />
                        <line
                          x1={sourcePos.x}
                          y1={sourcePos.y}
                          x2={targetPos.x}
                          y2={targetPos.y}
                          stroke={strokeColor}
                          strokeWidth={strokeWidth}
                          strokeDasharray={strokeDasharray}
                          opacity={opacity}
                          filter={isSelected ? "url(#glow-cyan)" : undefined}
                          className="transition-all duration-150 group-hover:opacity-100"
                        />
                        {/* Probability pill on correlation edge */}
                        {isCorrelation && isRelated && (
                          <g transform={`translate(${midX}, ${midY})`}>
                            <rect
                              x={-20}
                              y={-9}
                              width={40}
                              height={18}
                              rx={4}
                              fill="#091321"
                              stroke={isSelected ? "#38bdf8" : "#0891b2"}
                              strokeWidth={1}
                              opacity={0.9}
                            />
                            <text
                              textAnchor="middle"
                              dy={3.5}
                              fill={isSelected ? "#38bdf8" : "#67e8f9"}
                              fontSize={9}
                              fontWeight="600"
                              fontFamily="monospace"
                            >
                              {(edge.probability ?? 0).toFixed(2)}
                            </text>
                          </g>
                        )}
                      </g>
                    );
                  })}

                  {/* Nodes Layer */}
                  {filteredData.nodes.map((node) => {
                    const pos = nodePositions[node.id];
                    if (!pos) return null;

                    const isSelected = selectedNode?.id === node.id;
                    const isHovered = hoveredNodeId === node.id;
                    const isHighlighted =
                      highlightNeighborIds === null || highlightNeighborIds.has(node.id);
                    const opacity = isHighlighted ? 1.0 : 0.25;

                    const isReport = node.type === "report";

                    return (
                      <g
                        key={node.id}
                        transform={`translate(${pos.x}, ${pos.y})`}
                        opacity={opacity}
                        className="cursor-pointer select-none transition-opacity duration-150"
                        onMouseEnter={() => setHoveredNodeId(node.id)}
                        onMouseLeave={() => setHoveredNodeId(null)}
                        onMouseDown={(e) => {
                          e.stopPropagation();
                          setDraggedNodeId(node.id);
                        }}
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedNode(node);
                          setSelectedEdge(null);
                        }}
                      >
                        {isReport ? (
                          // Report Node representation
                          <g>
                            {/* Selection Ring */}
                            {isSelected && (
                              <circle
                                r={26}
                                fill="none"
                                stroke="#38bdf8"
                                strokeWidth={3}
                                filter="url(#glow-cyan)"
                              />
                            )}
                            <circle
                              r={20}
                              fill="#0f172a"
                              stroke={isSelected ? "#38bdf8" : "#0284c7"}
                              strokeWidth={isSelected ? 2.5 : 1.8}
                              className="transition-colors hover:stroke-cyan"
                            />
                            {/* Document Icon centered */}
                            <path
                              d="M -5 -7 L 1 -7 L 5 -3 L 5 7 L -5 7 Z"
                              fill="#0284c7"
                              opacity={0.8}
                            />
                            <path d="M 1 -7 L 1 -3 L 5 -3 Z" fill="#38bdf8" />

                            {/* Label Text below node */}
                            <text
                              y={32}
                              textAnchor="middle"
                              fill="#f1f5f9"
                              fontSize={10.5}
                              fontWeight="600"
                              className="pointer-events-none drop-shadow"
                            >
                              {node.label.length > 24 ? node.label.slice(0, 24) + "…" : node.label}
                            </text>
                            {node.source_name && (
                              <text
                                y={44}
                                textAnchor="middle"
                                fill="#94a3b8"
                                fontSize={9}
                                className="pointer-events-none"
                              >
                                {node.source_name}
                              </text>
                            )}
                          </g>
                        ) : (
                          // Entity Node representation (Diamond / Pill)
                          <g>
                            {(() => {
                              const style = getEntityStyle(node.entity_type);
                              return (
                                <>
                                  {isSelected && (
                                    <circle
                                      r={17}
                                      fill="none"
                                      stroke={style.border}
                                      strokeWidth={2.5}
                                      filter="url(#glow-cyan)"
                                    />
                                  )}
                                  <polygon
                                    points="0,-12 12,0 0,12 -12,0"
                                    fill={style.bg}
                                    stroke={isSelected ? "#fff" : style.border}
                                    strokeWidth={isSelected ? 2.0 : 1.4}
                                    className="transition-colors"
                                  />
                                  {/* Small label */}
                                  <text
                                    y={22}
                                    textAnchor="middle"
                                    fill={style.text}
                                    fontSize={9.5}
                                    fontWeight="500"
                                    className="pointer-events-none drop-shadow"
                                  >
                                    {node.label.length > 18 ? node.label.slice(0, 18) + "…" : node.label}
                                  </text>
                                </>
                              );
                            })()}
                          </g>
                        )}
                      </g>
                    );
                  })}
                </g>
              </svg>
            )}
          </div>

          {/* Right Detail Drawer / Inspector */}
          {(selectedNode || selectedEdge) && (
            <div className="z-20 w-80 sm:w-96 border-l border-slate-800 bg-panel/95 p-5 shadow-2xl backdrop-blur flex flex-col justify-between overflow-y-auto">
              <div>
                <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                  <span className="text-xs font-semibold uppercase tracking-wider text-cyan flex items-center gap-1.5">
                    {selectedNode?.type === "report" && <FileText size={14} />}
                    {selectedNode?.type === "entity" && <Tag size={14} />}
                    {selectedEdge && <Workflow size={14} />}
                    {selectedNode
                      ? selectedNode.type === "report"
                        ? "Report Details"
                        : "Entity Details"
                      : "Correlation Edge"}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedNode(null);
                      setSelectedEdge(null);
                    }}
                    className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
                  >
                    <X size={15} />
                  </button>
                </div>

                {/* Report Node Inspector */}
                {selectedNode && selectedNode.type === "report" && (
                  <div className="mt-4 space-y-4 text-xs">
                    <div>
                      <span className="text-slate-500">Report Title</span>
                      <h3 className="mt-0.5 text-sm font-semibold text-white leading-snug">
                        {selectedNode.label}
                      </h3>
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                      <div className="rounded-lg bg-slate-900 p-2">
                        <span className="text-slate-500 block">Source Feed</span>
                        <span className="font-medium text-slate-200">
                          {selectedNode.source_name || "Unknown"}
                        </span>
                      </div>
                      <div className="rounded-lg bg-slate-900 p-2">
                        <span className="text-slate-500 block">Published</span>
                        <span className="font-medium text-slate-200">
                          {selectedNode.published_at
                            ? new Date(selectedNode.published_at).toLocaleDateString()
                            : "N/A"}
                        </span>
                      </div>
                    </div>

                    <div>
                      <span className="text-slate-500 block mb-1.5 font-medium">
                        Connected Correlated Reports
                      </span>
                      <div className="max-h-40 divide-y divide-slate-800/80 overflow-y-auto rounded-lg border border-slate-800 bg-slate-900/50 p-2">
                        {data?.edges
                          .filter(
                            (e) =>
                              e.type === "correlation" &&
                              (e.source === selectedNode.id || e.target === selectedNode.id)
                          )
                          .map((e) => {
                            const otherId = e.source === selectedNode.id ? e.target : e.source;
                            const otherNode = nodesById[otherId];
                            return (
                              <div
                                key={e.id}
                                className="py-1.5 flex items-center justify-between cursor-pointer hover:text-cyan"
                                onClick={() => {
                                  setSelectedEdge(e);
                                  setSelectedNode(null);
                                }}
                              >
                                <span className="truncate pr-2 text-slate-300">
                                  {otherNode?.label || otherId}
                                </span>
                                <span
                                  className={`font-mono text-[11px] font-semibold ${
                                    e.is_related ? "text-cyan" : "text-slate-500"
                                  }`}
                                >
                                  P={e.probability?.toFixed(2)}
                                </span>
                              </div>
                            );
                          })}
                      </div>
                    </div>

                    <div>
                      <span className="text-slate-500 block mb-1.5 font-medium">
                        Extracted Entities Mentioned
                      </span>
                      <div className="flex flex-wrap gap-1.5">
                        {data?.edges
                          .filter((e) => e.type === "has_entity" && e.source === selectedNode.id)
                          .map((e) => {
                            const entNode = nodesById[e.target];
                            const style = getEntityStyle(entNode?.entity_type);
                            return (
                              <span
                                key={e.id}
                                onClick={() => {
                                  if (entNode) setSelectedNode(entNode);
                                }}
                                style={{ backgroundColor: style.bg, borderColor: style.border }}
                                className="cursor-pointer rounded border px-2 py-0.5 text-[11px] text-slate-200 hover:brightness-125"
                              >
                                {entNode?.label}
                              </span>
                            );
                          })}
                      </div>
                    </div>
                  </div>
                )}

                {/* Entity Node Inspector */}
                {selectedNode && selectedNode.type === "entity" && (
                  <div className="mt-4 space-y-4 text-xs">
                    <div>
                      <span className="text-slate-500">Entity Value</span>
                      <h3 className="mt-0.5 text-sm font-semibold text-white break-words">
                        {selectedNode.label}
                      </h3>
                    </div>

                    <div className="rounded-lg bg-slate-900 p-2.5">
                      <span className="text-slate-500 block">Category</span>
                      <span className="font-semibold text-amber-300 capitalize">
                        {selectedNode.entity_type?.replace("_", " ") || "Entity"}
                      </span>
                    </div>

                    <div>
                      <span className="text-slate-500 block mb-1.5 font-medium">
                        Referenced in Reports ({
                          data?.edges.filter((e) => e.type === "has_entity" && e.target === selectedNode.id).length
                        })
                      </span>
                      <div className="max-h-48 divide-y divide-slate-800 overflow-y-auto rounded-lg border border-slate-800 bg-slate-900/50 p-2">
                        {data?.edges
                          .filter((e) => e.type === "has_entity" && e.target === selectedNode.id)
                          .map((e) => {
                            const repNode = nodesById[e.source];
                            return (
                              <div
                                key={e.id}
                                className="py-2 cursor-pointer hover:text-cyan"
                                onClick={() => {
                                  if (repNode) setSelectedNode(repNode);
                                }}
                              >
                                <p className="font-medium text-slate-200">{repNode?.label}</p>
                                <span className="text-[10px] text-slate-500">{repNode?.source_name}</span>
                              </div>
                            );
                          })}
                      </div>
                    </div>
                  </div>
                )}

                {/* Correlation Edge Inspector */}
                {selectedEdge && (
                  <div className="mt-4 space-y-4 text-xs">
                    {/* Pair Endpoints */}
                    <div className="rounded-lg bg-slate-900 p-3 space-y-2">
                      <div>
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider block">
                          Report 1
                        </span>
                        <span className="font-semibold text-slate-200">
                          {nodesById[selectedEdge.source]?.label || selectedEdge.source}
                        </span>
                        <span className="block text-[10px] text-slate-500">
                          {nodesById[selectedEdge.source]?.source_name}
                        </span>
                      </div>
                      <div className="border-t border-slate-800 pt-2">
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider block">
                          Report 2
                        </span>
                        <span className="font-semibold text-slate-200">
                          {nodesById[selectedEdge.target]?.label || selectedEdge.target}
                        </span>
                        <span className="block text-[10px] text-slate-500">
                          {nodesById[selectedEdge.target]?.source_name}
                        </span>
                      </div>
                    </div>

                    {/* Probability & Decision Gauge */}
                    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="font-semibold text-white">Correlation Probability</span>
                        <span
                          className={`font-mono text-sm font-bold ${
                            selectedEdge.is_related ? "text-cyan" : "text-slate-400"
                          }`}
                        >
                          {((selectedEdge.probability ?? 0) * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
                        <div
                          className={`h-full transition-all ${
                            selectedEdge.is_related ? "bg-cyan" : "bg-slate-600"
                          }`}
                          style={{ width: `${(selectedEdge.probability ?? 0) * 100}%` }}
                        />
                      </div>
                      <div className="mt-2 flex items-center justify-between text-[11px]">
                        <span className="text-slate-400">
                          Decision Threshold: {selectedEdge.prediction_threshold?.toFixed(2) ?? "0.35"}
                        </span>
                        <span
                          className={`font-semibold uppercase tracking-wider ${
                            selectedEdge.is_related ? "text-emerald-400" : "text-slate-400"
                          }`}
                        >
                          {selectedEdge.label || (selectedEdge.is_related ? "related" : "unrelated")}
                        </span>
                      </div>
                    </div>

                    {/* 6-Feature Similarity Dimensions */}
                    <div>
                      <span className="text-slate-400 block mb-2 font-semibold">
                        Feature Similarity Dimensions (Model Inputs)
                      </span>
                      <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-900/50 p-2.5">
                        {Object.entries(selectedEdge.feature_similarities || {}).map(
                          ([feat, score]) => {
                            const formattedName = feat
                              .replace("_similarity", "")
                              .replace(/_/g, " ")
                              .replace(/\b\w/g, (c) => c.toUpperCase());
                            return (
                              <div key={feat}>
                                <div className="flex items-center justify-between text-[11px] mb-0.5">
                                  <span className="text-slate-300">{formattedName}</span>
                                  <span className="font-mono text-slate-400">
                                    {(score as number).toFixed(3)}
                                  </span>
                                </div>
                                <div className="h-1.5 w-full rounded-full bg-slate-800 overflow-hidden">
                                  <div
                                    className="h-full bg-cyan/70"
                                    style={{ width: `${Math.min(100, Math.max(0, (score as number) * 100))}%` }}
                                  />
                                </div>
                              </div>
                            );
                          }
                        )}
                      </div>
                    </div>

                    {/* Predictor Metadata */}
                    <div className="rounded-lg bg-slate-900/60 p-2.5 text-[11px] text-slate-400 space-y-1">
                      <div className="flex justify-between">
                        <span>Predictor:</span>
                        <span className="text-slate-200">
                          {selectedEdge.predictor_type || "evidence_aware_random_forest"}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>Model Version:</span>
                        <span className="text-slate-200">
                          {selectedEdge.predictor_version || "f1-improvement-v3"}
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <button
                type="button"
                onClick={() => {
                  setSelectedNode(null);
                  setSelectedEdge(null);
                }}
                className="mt-4 w-full rounded-lg border border-slate-700 bg-slate-900 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
              >
                Close Inspector
              </button>
            </div>
          )}
        </div>
      ) : (
        /* Accessible Table Alternative */
        <div className="rounded-xl border border-slate-800 bg-panel overflow-hidden">
          <div className="flex border-b border-slate-800 bg-slate-900/50 text-xs">
            <button
              type="button"
              onClick={() => setTableTab("correlations")}
              className={`px-5 py-3 font-semibold transition ${
                tableTab === "correlations"
                  ? "border-b-2 border-cyan text-cyan bg-slate-900"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              Correlated Pairs ({filteredData.edges.filter((e) => e.type === "correlation").length})
            </button>
            <button
              type="button"
              onClick={() => setTableTab("reports")}
              className={`px-5 py-3 font-semibold transition ${
                tableTab === "reports"
                  ? "border-b-2 border-cyan text-cyan bg-slate-900"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              Reports ({filteredData.reportCount})
            </button>
            <button
              type="button"
              onClick={() => setTableTab("entities")}
              className={`px-5 py-3 font-semibold transition ${
                tableTab === "entities"
                  ? "border-b-2 border-cyan text-cyan bg-slate-900"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              Extracted Entities ({filteredData.entityCount})
            </button>
          </div>

          <div className="p-4 overflow-x-auto">
            {tableTab === "correlations" && (
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="border-b border-slate-800 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="py-2.5 px-3">First Report</th>
                    <th className="py-2.5 px-3">Second Report</th>
                    <th className="py-2.5 px-3">Probability</th>
                    <th className="py-2.5 px-3">Decision</th>
                    <th className="py-2.5 px-3">Predictor</th>
                    <th className="py-2.5 px-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {filteredData.edges
                    .filter((e) => e.type === "correlation")
                    .map((edge) => (
                      <tr key={edge.id} className="hover:bg-slate-900/40">
                        <td className="py-2.5 px-3">
                          <p className="font-medium text-white">
                            {nodesById[edge.source]?.label || edge.source}
                          </p>
                          <span className="text-[10px] text-slate-500">
                            {nodesById[edge.source]?.source_name}
                          </span>
                        </td>
                        <td className="py-2.5 px-3">
                          <p className="font-medium text-white">
                            {nodesById[edge.target]?.label || edge.target}
                          </p>
                          <span className="text-[10px] text-slate-500">
                            {nodesById[edge.target]?.source_name}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 font-mono font-semibold text-cyan">
                          {edge.probability?.toFixed(3)}
                        </td>
                        <td className="py-2.5 px-3">
                          <span
                            className={`rounded px-2 py-0.5 text-[10px] font-semibold uppercase ${
                              edge.is_related
                                ? "bg-emerald-950/80 text-emerald-300 border border-emerald-800/60"
                                : "bg-slate-900 text-slate-400 border border-slate-800"
                            }`}
                          >
                            {edge.label}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-slate-400">
                          {edge.predictor_version || "f1-improvement-v3"}
                        </td>
                        <td className="py-2.5 px-3 text-right">
                          <button
                            type="button"
                            onClick={() => {
                              setSelectedEdge(edge);
                              setViewMode("graph");
                            }}
                            className="text-cyan hover:underline"
                          >
                            Inspect &rarr;
                          </button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            )}

            {tableTab === "reports" && (
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="border-b border-slate-800 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="py-2.5 px-3">Title</th>
                    <th className="py-2.5 px-3">Source Feed</th>
                    <th className="py-2.5 px-3">Published Date</th>
                    <th className="py-2.5 px-3">Document ID</th>
                    <th className="py-2.5 px-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {filteredData.nodes
                    .filter((n) => n.type === "report")
                    .map((node) => (
                      <tr key={node.id} className="hover:bg-slate-900/40">
                        <td className="py-2.5 px-3 font-medium text-white">{node.label}</td>
                        <td className="py-2.5 px-3 text-slate-400">{node.source_name}</td>
                        <td className="py-2.5 px-3 text-slate-400">
                          {node.published_at ? new Date(node.published_at).toLocaleDateString() : "N/A"}
                        </td>
                        <td className="py-2.5 px-3 font-mono text-[11px] text-slate-500">
                          {node.id.replace("report:", "").slice(0, 8)}…
                        </td>
                        <td className="py-2.5 px-3 text-right">
                          <button
                            type="button"
                            onClick={() => {
                              setSelectedNode(node);
                              setViewMode("graph");
                            }}
                            className="text-cyan hover:underline"
                          >
                            Inspect &rarr;
                          </button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            )}

            {tableTab === "entities" && (
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="border-b border-slate-800 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="py-2.5 px-3">Entity Name</th>
                    <th className="py-2.5 px-3">Type</th>
                    <th className="py-2.5 px-3">Referenced In</th>
                    <th className="py-2.5 px-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {filteredData.nodes
                    .filter((n) => n.type === "entity")
                    .map((node) => {
                      const style = getEntityStyle(node.entity_type);
                      const mentions = data?.edges.filter(
                        (e) => e.type === "has_entity" && e.target === node.id
                      ).length;
                      return (
                        <tr key={node.id} className="hover:bg-slate-900/40">
                          <td className="py-2.5 px-3 font-medium text-white">{node.label}</td>
                          <td className="py-2.5 px-3">
                            <span
                              style={{ backgroundColor: style.bg, borderColor: style.border }}
                              className="rounded border px-2 py-0.5 text-[10px] font-medium text-slate-200 capitalize"
                            >
                              {node.entity_type?.replace("_", " ")}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-slate-400">{mentions} reports</td>
                          <td className="py-2.5 px-3 text-right">
                            <button
                              type="button"
                              onClick={() => {
                                setSelectedNode(node);
                                setViewMode("graph");
                              }}
                              className="text-cyan hover:underline"
                            >
                              Inspect &rarr;
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
