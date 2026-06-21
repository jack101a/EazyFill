import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BrainCircuit, Check, RefreshCw, Save, Upload, X } from "lucide-react";
import {
  approveCaptchaProposal,
  captchaModelQueryKeys,
  fetchCaptchaModels,
  fetchCaptchaProposals,
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
  const models = query.data?.models || [];
  const mappings = query.data?.field_mappings || [];
  const proposals = Array.isArray(proposalQuery.data) ? proposalQuery.data : [];
  const activeModels = models.filter((model) => model.status === "active");

  async function refreshAll() {
    await Promise.all([query.refetch(), proposalQuery.refetch()]);
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
    if (!modelId) {
      showToast?.("Select a model before approving", "error");
      return;
    }
    setSaving(`approve-${proposal.id}`);
    try {
      await approveCaptchaProposal(proposal.id, modelId);
      await refreshAll();
      showToast?.("CAPTCHA route approved", "success");
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
                  >
                    <option value="">Select model</option>
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
          <p className={`mt-1 text-xs ${t_textMuted}`}>The backend solves only when the extension sends a matching domain and field name.</p>
        </div>
        <DataTable
          columns={[
            { key: "domain", label: "Domain" },
            { key: "field_name", label: "Field" },
            { key: "source_selector", label: "Source", render: (row) => <span className="font-mono text-xs">{row.source_selector || "-"}</span> },
            { key: "target_selector", label: "Target", render: (row) => <span className="font-mono text-xs">{row.target_selector || "-"}</span> },
            { key: "ai_model_filename", label: "Model", render: (row) => <span className="font-mono text-xs">{row.ai_model_filename || `#${row.ai_model_id}`}</span> },
          ]}
          rows={mappings}
          emptyTitle="No field mappings"
          emptyDescription="Create mappings for domains that need a specific CAPTCHA model."
        />
      </section>
    </div>
  );
}
