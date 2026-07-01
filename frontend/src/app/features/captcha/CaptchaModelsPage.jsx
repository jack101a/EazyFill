import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BrainCircuit, Check, RefreshCw, Save, Upload, X } from "lucide-react";
import {
  approveCaptchaProposal,
  bulkUpdateCaptchaMappingModel,
  captchaModelQueryKeys,
  fetchCaptchaModels,
  fetchCaptchaProposals,
  fetchCaptchaSamples,
  rejectCaptchaProposal,
  setCaptchaMapping,
  uploadCaptchaModel,
} from "../../../api/captchaModels";
import { EmptyState } from "../../components/EmptyState";
import { usePageTitle } from "../../hooks/usePageTitle";
import { useThemeContext } from "../../context/ThemeContext";

const defaultUpload = { ai_model_name: "", version: "v1", notes: "", file: null };
const defaultMapping = {
  domain: "",
  field_name: "",
  source_selector: "",
  target_selector: "",
  ai_model_id: "",
};

function compactModelLabel(model) {
  if (!model) return "";
  return `${model.ai_model_name || "Model"} ${model.version || ""}`.trim();
}

function formatDateTime(value) {
  return value ? new Date(value).toLocaleString() : "-";
}

function DataTable({ columns, rows, emptyTitle, emptyDescription }) {
  const { isDark } = useThemeContext();
  const border = isDark ? "border-white/[0.07]" : "border-slate-200";
  if (!rows.length) {
    return <EmptyState icon={BrainCircuit} title={emptyTitle} description={emptyDescription} />;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead>
          <tr className={`border-b ${border}`}>
            {columns.map((column) => <th key={column.key} className="p-3 text-xs font-bold uppercase">{column.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id || row.domain || index} className={`border-b ${border}`}>
              {columns.map((column) => (
                <td key={column.key} className="p-3 align-top">{column.render ? column.render(row) : row[column.key] || "-"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TextInput({ label, value, onChange, placeholder = "" }) {
  const { isDark } = useThemeContext();
  return (
    <label className="grid gap-1 text-sm font-medium">
      {label}
      <input
        className={`h-10 border px-3 text-sm outline-none transition focus:border-[#A83AFB] ${isDark ? "border-white/10 bg-slate-950/70 text-slate-100" : "border-slate-200 bg-white text-slate-900"}`}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function SelectInput({ label, value, onChange, children }) {
  const { isDark } = useThemeContext();
  return (
    <label className="grid gap-1 text-sm font-medium">
      {label}
      <select
        className={`h-10 border px-3 text-sm outline-none transition focus:border-[#A83AFB] ${isDark ? "border-white/10 bg-slate-950/70 text-slate-100" : "border-slate-200 bg-white text-slate-900"}`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {children}
      </select>
    </label>
  );
}

export function CaptchaModelsPage({ showToast }) {
  usePageTitle("CAPTCHA Models");
  const { isDark, t_textHeading, t_textMuted, glassButton, glassPanel } = useThemeContext();
  const [uploadForm, setUploadForm] = useState(defaultUpload);
  const [mappingForm, setMappingForm] = useState(defaultMapping);
  const [proposalModels, setProposalModels] = useState({});
  const [mappingFilters, setMappingFilters] = useState({ domain: "", source: "", target: "" });
  const [selectedMappings, setSelectedMappings] = useState([]);
  const [bulkModelId, setBulkModelId] = useState("");
  const [sampleFilters, setSampleFilters] = useState({ status: "all", domain: "" });
  const [saving, setSaving] = useState("");
  const query = useQuery({
    queryKey: captchaModelQueryKeys.root,
    queryFn: fetchCaptchaModels,
    staleTime: 20_000,
  });
  const proposalQuery = useQuery({
    queryKey: [...captchaModelQueryKeys.root, "proposals", "pending"],
    queryFn: () => fetchCaptchaProposals("pending"),
    staleTime: 20_000,
  });
  const sampleQuery = useQuery({
    queryKey: [...captchaModelQueryKeys.root, "samples", sampleFilters],
    queryFn: () => fetchCaptchaSamples(sampleFilters),
    staleTime: 20_000,
  });
  const models = query.data?.models || [];
  const mappings = query.data?.field_mappings || [];
  const proposals = Array.isArray(proposalQuery.data) ? proposalQuery.data : [];
  const samples = sampleQuery.data?.samples || [];
  const activeModels = models.filter((model) => model.status === "active");
  const filteredMappings = mappings.filter((mapping) => {
    const haystack = {
      domain: String(mapping.domain || "").toLowerCase(),
      source: String(mapping.source_selector || "").toLowerCase(),
      target: String(mapping.target_selector || "").toLowerCase(),
    };
    return (!mappingFilters.domain || haystack.domain.includes(mappingFilters.domain.toLowerCase()))
      && (!mappingFilters.source || haystack.source.includes(mappingFilters.source.toLowerCase()))
      && (!mappingFilters.target || haystack.target.includes(mappingFilters.target.toLowerCase()));
  });
  const visibleMappingIds = filteredMappings.map((mapping) => Number(mapping.id)).filter(Boolean);
  const selectedVisibleCount = visibleMappingIds.filter((id) => selectedMappings.includes(id)).length;

  async function refreshAll() {
    await Promise.all([query.refetch(), proposalQuery.refetch(), sampleQuery.refetch()]);
  }

  function toggleMapping(mappingId) {
    const id = Number(mappingId);
    setSelectedMappings((current) => current.includes(id)
      ? current.filter((item) => item !== id)
      : [...current, id]);
  }

  function toggleAllVisibleMappings() {
    setSelectedMappings((current) => {
      const visible = new Set(visibleMappingIds);
      const allVisibleSelected = visibleMappingIds.length > 0 && visibleMappingIds.every((id) => current.includes(id));
      if (allVisibleSelected) return current.filter((id) => !visible.has(id));
      return Array.from(new Set([...current, ...visibleMappingIds]));
    });
  }

  async function saveBulkModelUpdate() {
    setSaving("bulk-mapping");
    try {
      await bulkUpdateCaptchaMappingModel({
        mapping_ids: selectedMappings,
        ai_model_id: Number(bulkModelId),
      });
      setSelectedMappings([]);
      setBulkModelId("");
      await refreshAll();
      showToast?.("Selected mappings updated", "success");
    } catch (error) {
      showToast?.(error.message || "Could not update mappings", "error");
    } finally {
      setSaving("");
    }
  }

  async function saveUpload() {
    setSaving("upload");
    try {
      await uploadCaptchaModel(uploadForm);
      setUploadForm(defaultUpload);
      await refreshAll();
      showToast?.("Model uploaded", "success");
    } catch (error) {
      showToast?.(error.message || "Could not upload model", "error");
    } finally {
      setSaving("");
    }
  }

  async function saveMapping() {
    setSaving("mapping");
    try {
      await setCaptchaMapping({ ...mappingForm, task_type: "image", ai_model_id: Number(mappingForm.ai_model_id) });
      setMappingForm(defaultMapping);
      await refreshAll();
      showToast?.("Field mapping saved", "success");
    } catch (error) {
      showToast?.(error.message || "Could not save field mapping", "error");
    } finally {
      setSaving("");
    }
  }

  async function approveProposal(proposal) {
    const modelId = proposalModels[proposal.id];
    setSaving(`approve-${proposal.id}`);
    try {
      await approveCaptchaProposal(proposal.id, modelId);
      await refreshAll();
      showToast?.(modelId ? "CAPTCHA route approved with selected model" : "CAPTCHA route approved", "success");
    } catch (error) {
      showToast?.(error.message || "Could not approve route", "error");
    } finally {
      setSaving("");
    }
  }

  async function rejectProposal(proposal) {
    setSaving(`reject-${proposal.id}`);
    try {
      await rejectCaptchaProposal(proposal.id);
      await refreshAll();
      showToast?.("CAPTCHA route rejected", "success");
    } catch (error) {
      showToast?.(error.message || "Could not reject route", "error");
    } finally {
      setSaving("");
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className={`text-xs font-bold uppercase ${t_textMuted}`}>CAPTCHA Routing</p>
          <h1 className={`mt-1 text-2xl font-bold ${t_textHeading}`}>Models and mappings</h1>
          <p className={`mt-1 max-w-3xl text-sm ${t_textMuted}`}>Manage exact ONNX model selection for CAPTCHA solves. Each extension CAPTCHA field must map to the model trained for that CAPTCHA.</p>
        </div>
        <button type="button" className={glassButton} onClick={refreshAll} disabled={query.isFetching || proposalQuery.isFetching}>
          <RefreshCw size={15} className={query.isFetching || proposalQuery.isFetching ? "animate-spin" : ""} />
          Refresh
        </button>
      </header>

      {query.error ? (
        <div className="border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">
          {query.error.message || "CAPTCHA model routing could not be loaded."}
        </div>
      ) : null}

      {proposalQuery.error ? (
        <div className="border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">
          {proposalQuery.error.message || "CAPTCHA route requests could not be loaded."}
        </div>
      ) : null}

      <section className={`border ${glassPanel}`}>
        <div className={`border-b p-5 ${isDark ? "border-white/[0.07]" : "border-slate-200"}`}>
          <h2 className={`text-base font-semibold ${t_textHeading}`}>Model registry</h2>
          <p className={`mt-1 text-xs ${t_textMuted}`}>Active ONNX image CAPTCHA models available for exact field mappings.</p>
        </div>
        <DataTable
          columns={[
            { key: "id", label: "ID", render: (row) => <span className="font-mono">#{row.id}</span> },
            { key: "ai_model_name", label: "Model" },
            { key: "version", label: "Version" },
            { key: "ai_model_filename", label: "File", render: (row) => <span className="font-mono text-xs">{row.ai_model_filename}</span> },
            { key: "lifecycle_state", label: "State" },
          ]}
          rows={models}
          emptyTitle="No models registered"
          emptyDescription="Upload an ONNX model before assigning CAPTCHA fields."
        />
      </section>

      <section className={`grid gap-4 border p-5 lg:grid-cols-2 ${glassPanel}`}>
        <div>
          <div className="mb-4 flex items-center gap-2">
            <Upload size={18} className="text-[#FF5FB8]" />
            <h2 className={`text-base font-semibold ${t_textHeading}`}>Upload ONNX model</h2>
          </div>
          <div className="grid gap-3">
            <TextInput label="Model name" value={uploadForm.ai_model_name} placeholder="Login captcha OCR" onChange={(ai_model_name) => setUploadForm((current) => ({ ...current, ai_model_name }))} />
            <TextInput label="Version" value={uploadForm.version} placeholder="v1" onChange={(version) => setUploadForm((current) => ({ ...current, version }))} />
            <TextInput label="Notes" value={uploadForm.notes} placeholder="Trained for example.com login CAPTCHA" onChange={(notes) => setUploadForm((current) => ({ ...current, notes }))} />
            <label className="grid gap-1 text-sm font-medium">
              ONNX file
              <input
                className={`h-10 border px-3 py-2 text-sm outline-none transition file:mr-3 file:border-0 file:bg-transparent file:text-sm file:font-semibold ${isDark ? "border-white/10 bg-slate-950/70 text-slate-100 file:text-[#FF5FB8]" : "border-slate-200 bg-white text-slate-900 file:text-[#8B5CF6]"}`}
                type="file"
                accept=".onnx"
                onChange={(event) => setUploadForm((current) => ({ ...current, file: event.target.files?.[0] || null }))}
              />
            </label>
            <button type="button" className={glassButton} onClick={saveUpload} disabled={saving === "upload" || !uploadForm.ai_model_name || !uploadForm.file}>
              <Upload size={15} />
              Upload model
            </button>
          </div>
        </div>
        <div>
          <h2 className={`mb-4 text-base font-semibold ${t_textHeading}`}>CAPTCHA field mapping</h2>
          <div className="grid gap-3">
            <TextInput label="Domain" value={mappingForm.domain} placeholder="example.com" onChange={(domain) => setMappingForm((current) => ({ ...current, domain }))} />
            <TextInput label="Field name" value={mappingForm.field_name} placeholder="login_captcha" onChange={(field_name) => setMappingForm((current) => ({ ...current, field_name }))} />
            <TextInput label="Source selector" value={mappingForm.source_selector} placeholder="#captcha-img" onChange={(source_selector) => setMappingForm((current) => ({ ...current, source_selector }))} />
            <TextInput label="Target selector" value={mappingForm.target_selector} placeholder="#captcha-input" onChange={(target_selector) => setMappingForm((current) => ({ ...current, target_selector }))} />
            <SelectInput label="Model" value={mappingForm.ai_model_id} onChange={(ai_model_id) => setMappingForm((current) => ({ ...current, ai_model_id }))}>
              <option value="">Select model</option>
              {activeModels.map((model) => <option key={model.id} value={model.id}>{compactModelLabel(model)} - {model.ai_model_filename}</option>)}
            </SelectInput>
            <button type="button" className={glassButton} onClick={saveMapping} disabled={saving === "mapping" || !mappingForm.domain || !mappingForm.field_name || !mappingForm.ai_model_id}>
              <Save size={15} />
              Save mapping
            </button>
          </div>
        </div>
      </section>

      <section className={`border ${glassPanel}`}>
        <div className={`border-b p-5 ${isDark ? "border-white/[0.07]" : "border-slate-200"}`}>
          <h2 className={`text-base font-semibold ${t_textHeading}`}>Pending CAPTCHA requests</h2>
          <p className={`mt-1 text-xs ${t_textMuted}`}>Routes submitted from extensions. Approving one creates a reusable pre-approved mapping for future users with the same selectors.</p>
        </div>
        <DataTable
          columns={[
            { key: "domain", label: "Domain" },
            { key: "proposed_field_name", label: "Field", render: (row) => <span className="font-mono text-xs">{row.proposed_field_name}</span> },
            { key: "source_selector", label: "Source", render: (row) => <span className="font-mono text-xs">{row.source_selector || "-"}</span> },
            { key: "target_selector", label: "Target", render: (row) => <span className="font-mono text-xs">{row.target_selector || "-"}</span> },
            { key: "sample_count", label: "Samples", render: (row) => row.sample_count || 0 },
            {
              key: "approve",
              label: "Approve",
              render: (row) => (
                <div className="flex min-w-[260px] flex-wrap gap-2">
                  <select
                    className={`h-9 min-w-[170px] border px-2 text-xs outline-none ${isDark ? "border-white/10 bg-slate-950/70 text-slate-100" : "border-slate-200 bg-white text-slate-900"}`}
                    value={proposalModels[row.id] || ""}
                    onChange={(event) => setProposalModels((current) => ({ ...current, [row.id]: event.target.value }))}
                    title="Optional. Leave blank to approve the selector route with the first active image model."
                  >
                    <option value="">Auto model</option>
                    {activeModels.map((model) => <option key={model.id} value={model.id}>{compactModelLabel(model)}</option>)}
                  </select>
                  <button type="button" className={glassButton} onClick={() => approveProposal(row)} disabled={saving === `approve-${row.id}`}>
                    <Check size={14} />
                    Approve
                  </button>
                  <button type="button" className={glassButton} onClick={() => rejectProposal(row)} disabled={saving === `reject-${row.id}`}>
                    <X size={14} />
                    Reject
                  </button>
                </div>
              ),
            },
          ]}
          rows={proposals}
          emptyTitle="No pending requests"
          emptyDescription="New extension routes appear here when they are not already pre-approved."
        />
      </section>

      <section className={`border ${glassPanel}`}>
        <div className={`border-b p-5 ${isDark ? "border-white/[0.07]" : "border-slate-200"}`}>
          <h2 className={`text-base font-semibold ${t_textHeading}`}>Active field mappings</h2>
          <p className={`mt-1 text-xs ${t_textMuted}`}>Filter mappings, select one or many rows, then move them to a newer model by domain, path selector, source, or target.</p>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <TextInput label="Domain filter" value={mappingFilters.domain} placeholder="sarathi.parivahan.gov.in" onChange={(domain) => setMappingFilters((current) => ({ ...current, domain }))} />
            <TextInput label="Source selector filter" value={mappingFilters.source} placeholder="#captcha-img" onChange={(source) => setMappingFilters((current) => ({ ...current, source }))} />
            <TextInput label="Target selector filter" value={mappingFilters.target} placeholder="#captcha-input" onChange={(target) => setMappingFilters((current) => ({ ...current, target }))} />
          </div>
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <button type="button" className={glassButton} onClick={toggleAllVisibleMappings} disabled={!visibleMappingIds.length}>
              {visibleMappingIds.length > 0 && selectedVisibleCount === visibleMappingIds.length ? "Clear visible" : "Select visible"}
            </button>
            <div className="min-w-[240px] flex-1">
              <SelectInput label="Update selected to model" value={bulkModelId} onChange={setBulkModelId}>
                <option value="">Select model</option>
                {activeModels.map((model) => <option key={model.id} value={model.id}>{compactModelLabel(model)} - {model.ai_model_filename}</option>)}
              </SelectInput>
            </div>
            <button type="button" className={glassButton} onClick={saveBulkModelUpdate} disabled={saving === "bulk-mapping" || !bulkModelId || !selectedMappings.length}>
              <Save size={15} />
              Update {selectedMappings.length ? `${selectedMappings.length} selected` : "selected"}
            </button>
          </div>
        </div>
        <DataTable
          columns={[
            {
              key: "select",
              label: "",
              render: (row) => (
                <input
                  type="checkbox"
                  checked={selectedMappings.includes(Number(row.id))}
                  onChange={() => toggleMapping(row.id)}
                  aria-label={`Select mapping ${row.field_name || row.id}`}
                />
              ),
            },
            { key: "domain", label: "Domain" },
            { key: "field_name", label: "Field" },
            { key: "source_selector", label: "Source", render: (row) => <span className="font-mono text-xs">{row.source_selector || "-"}</span> },
            { key: "target_selector", label: "Target", render: (row) => <span className="font-mono text-xs">{row.target_selector || "-"}</span> },
            { key: "ai_model_filename", label: "Model", render: (row) => <span className="font-mono text-xs">{row.ai_model_filename || `#${row.ai_model_id}`}</span> },
          ]}
          rows={filteredMappings}
          emptyTitle="No field mappings"
          emptyDescription="Create mappings for domains that need a specific CAPTCHA model."
        />
      </section>

      <section className={`border ${glassPanel}`}>
        <div className={`border-b p-5 ${isDark ? "border-white/[0.07]" : "border-slate-200"}`}>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h2 className={`text-base font-semibold ${t_textHeading}`}>Training samples</h2>
              <p className={`mt-1 text-xs ${t_textMuted}`}>Collected CAPTCHA images with the user-entered answer stored as the training label.</p>
              <p className={`mt-2 text-xs ${t_textMuted}`}>
                Queued {sampleQuery.data?.counts?.queued || 0} · Labeled {sampleQuery.data?.counts?.labeled || 0} · Consumed {sampleQuery.data?.counts?.consumed || 0}
              </p>
            </div>
            <div className="grid min-w-[360px] gap-3 sm:grid-cols-2">
              <SelectInput label="Sample status" value={sampleFilters.status} onChange={(status) => setSampleFilters((current) => ({ ...current, status }))}>
                <option value="all">All samples</option>
                <option value="queued">Queued</option>
                <option value="labeled">Labeled</option>
                <option value="consumed">Consumed</option>
                <option value="rejected">Rejected</option>
              </SelectInput>
              <TextInput label="Sample domain" value={sampleFilters.domain} placeholder="example.com" onChange={(domain) => setSampleFilters((current) => ({ ...current, domain }))} />
            </div>
          </div>
        </div>
        <DataTable
          columns={[
            {
              key: "image",
              label: "Image",
              render: (row) => row.image_url ? (
                <img
                  src={row.image_url}
                  alt={`CAPTCHA sample ${row.id}`}
                  className={`h-12 max-w-[160px] border object-contain ${isDark ? "border-white/10 bg-white" : "border-slate-200 bg-slate-50"}`}
                />
              ) : <span className={t_textMuted}>Missing file</span>,
            },
            { key: "label_text", label: "Label", render: (row) => <span className="font-mono text-sm">{row.label_text || "-"}</span> },
            { key: "domain", label: "Domain" },
            { key: "field_name", label: "Field", render: (row) => <span className="font-mono text-xs">{row.field_name || "-"}</span> },
            { key: "status", label: "Status" },
            { key: "created_at", label: "Collected", render: (row) => formatDateTime(row.created_at) },
          ]}
          rows={samples}
          emptyTitle="No training samples"
          emptyDescription="Samples appear here when users submit CAPTCHA routes with learning consent and the typed answer."
        />
      </section>
    </div>
  );
}
