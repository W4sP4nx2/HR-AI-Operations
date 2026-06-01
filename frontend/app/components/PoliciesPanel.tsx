"use client";

/**
 * PoliciesPanel — HR policy document management.
 *
 * HR administrators drag-and-drop or click to upload PDF policy documents.
 * Each upload is extracted, chunked and ingested into the vector store so the
 * Policy Q&A agent and Chat assistant have current, cited knowledge.
 *
 * The panel lists all ingested documents with their chunk count, char count
 * and ingestion status, and lets admins remove stale ones.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { UploadCloud, FileText, Trash2, Loader2, CheckCircle, AlertCircle } from "lucide-react";
import { api, type PolicyDoc } from "../../lib/api";
import { useToast } from "./Toast";

type UploadState = { status: "idle" } | { status: "uploading"; name: string } | { status: "done"; doc: PolicyDoc; qdrant: boolean } | { status: "error"; name: string; message: string };

export default function PoliciesPanel() {
  const [policies, setPolicies] = useState<PolicyDoc[]>([]);
  const [upload, setUpload] = useState<UploadState>({ status: "idle" });
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const toast = useToast();

  const load = useCallback(async () => {
    try { setPolicies(await api.policies()); } catch { /* keep */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  const ingest = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setUpload({ status: "error", name: file.name, message: "Only PDF files are accepted." });
      return;
    }
    setUpload({ status: "uploading", name: file.name });
    try {
      const env = await api.ingestPolicy(file);
      if (env.success && env.data) {
        const d = env.data as PolicyDoc & { vector_ingested: boolean };
        setUpload({ status: "done", doc: d, qdrant: d.vector_ingested });
        toast.notify(`Ingested ${d.filename}`, "success");
        await load();
      } else {
        setUpload({ status: "error", name: file.name, message: env.error ?? "Ingestion failed." });
        if (env.status === "unavailable") toast.notify(env.error ?? "Capability unavailable.", "warning");
        else toast.notify(env.error ?? "Ingestion failed.", "error");
      }
    } catch (e) {
      setUpload({ status: "error", name: file.name, message: (e as Error).message });
      toast.notifyError(e);
    }
  };

  const remove = async (docId: string, name: string) => {
    try {
      await api.deletePolicy(docId);
      await load();
      // Soft-delete → offer an Undo that restores + re-embeds.
      toast.notify(`Removed ${name}`, "warning", {
        label: "Undo",
        onClick: async () => {
          try {
            await api.restorePolicy(docId);
            await load();
            toast.notify(`Restored ${name}`, "success");
          } catch (e) {
            toast.notifyError(e);
          }
        },
      });
    } catch (e) {
      toast.notifyError(e);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) ingest(file);
  };

  return (
    <div className="space-y-6">
      {/* Upload zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-8 py-12 transition ${
          dragging
            ? "border-brand-magenta bg-brand-magenta/5"
            : "border-brand-purple/20 bg-white hover:border-brand-magenta/50"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) ingest(f); e.target.value = ""; }}
        />
        <UploadCloud size={36} className={dragging ? "text-brand-magenta" : "text-brand-purple/40"} />
        <div className="text-center">
          <p className="font-medium text-brand-purple">
            {dragging ? "Drop to ingest" : "Drag & drop a PDF, or click to browse"}
          </p>
          <p className="mt-1 text-xs text-ink-700/60">
            Policy documents are extracted, chunked and loaded into the vector store
          </p>
        </div>
      </div>

      {/* Upload feedback */}
      {upload.status === "uploading" && (
        <div className="flex items-center gap-3 rounded-xl bg-brand-cream px-4 py-3 text-sm">
          <Loader2 size={16} className="animate-spin text-brand-magenta" />
          <span>Ingesting <strong>{upload.name}</strong>…</span>
        </div>
      )}
      {upload.status === "done" && (
        <div className="flex items-start gap-3 rounded-xl border border-green-200 bg-green-50 px-4 py-3 text-sm">
          <CheckCircle size={16} className="mt-0.5 text-green-600" />
          <div>
            <p className="font-medium text-green-700">
              {upload.doc.filename} ingested — {upload.doc.chunks} chunks, {upload.doc.char_count.toLocaleString()} chars
            </p>
            {!upload.qdrant && (
              <p className="mt-0.5 text-xs text-amber-600">
                ⚠ Saved to registry only — vector store unavailable (start Qdrant for semantic search).
              </p>
            )}
          </div>
        </div>
      )}
      {upload.status === "error" && (
        <div className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm">
          <AlertCircle size={16} className="mt-0.5 text-red-500" />
          <div>
            <p className="font-medium text-red-700">{upload.name}</p>
            <p className="text-red-600">{upload.message}</p>
          </div>
        </div>
      )}

      {/* Policy list */}
      <div>
        <h2 className="mb-3 text-sm font-semibold text-ink-700/70 uppercase tracking-wide">
          Loaded policies ({policies.length})
        </h2>
        {policies.length === 0 ? (
          <p className="rounded-2xl border border-brand-purple/10 bg-white px-6 py-8 text-center text-sm text-ink-700/60">
            No policies ingested yet. Upload a PDF above to get started.
          </p>
        ) : (
          <div className="overflow-hidden rounded-2xl border border-brand-purple/10 bg-white shadow-sm">
            {policies.map((p, i) => (
              <div
                key={p.doc_id}
                className={`flex items-center gap-4 px-5 py-3 text-sm ${i < policies.length - 1 ? "border-b border-brand-purple/5" : ""}`}
              >
                <FileText size={16} className="shrink-0 text-brand-magenta" />
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate text-brand-purple">{p.filename}</p>
                  <p className="text-xs text-ink-700/60 mt-0.5">
                    {p.chunks} chunks · {p.char_count.toLocaleString()} chars ·{" "}
                    <span className={p.status === "ingested" ? "text-green-600" : "text-amber-600"}>
                      {p.status}
                    </span>
                    {" · "}{new Date(p.ingested_at).toLocaleDateString()}
                  </p>
                </div>
                <p className="text-xs font-mono text-ink-700/40 hidden md:block truncate max-w-[180px]">
                  {p.doc_id}
                </p>
                <button
                  onClick={() => remove(p.doc_id, p.filename)}
                  title="Remove from registry (restorable)"
                  aria-label={`Remove policy ${p.filename}`}
                  className="shrink-0 rounded-lg p-1.5 text-ink-700/40 hover:bg-red-50 hover:text-red-500 transition"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
