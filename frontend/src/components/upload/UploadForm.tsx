"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Card } from "@/components/ui/Card";
import { Stepper } from "@/components/ui/Stepper";
import { DropZone } from "./DropZone";
import { validateFile } from "@/lib/upload";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";

const STEPS = ["Upload", "AI Analysis", "Review"];

/**
 * Owns the upload flow (spec 015 §2.3 / plan §3.5): validate → submitAnalysis → navigate to the
 * live processing screen. No external-account row, no recipient field (D2/D3). The server stays
 * authoritative — a slipped-through bad file surfaces the 011 400/413 as an inline error (EC-4).
 */
export function UploadForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onFile(file: File) {
    if (submitting) return; // ignore while a submit is in flight (AC-7, EC-9)
    const v = validateFile(file);
    if (!v.ok) {
      setError(v.message);
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const res = await getApiClient().submitAnalysis(file);
      router.push(`/jobs/${res.job_id}`);
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ApiError && err.status === 400) setError("Unsupported or empty file.");
      else if (err instanceof ApiError && err.status === 413) setError("File is too large.");
      else setError("Couldn't reach the server. Please try again.");
    }
  }

  return (
    <Card className="mx-auto w-full max-w-2xl" glow>
      <Stepper steps={STEPS} current={0} className="mb-6" />
      <h2 className="mb-5 text-h1 font-bold text-text-primary">Upload New Contract</h2>
      <DropZone onFile={onFile} disabled={submitting} />
      {error && (
        <p role="alert" className="mt-3 text-small text-risk-high">
          {error}
        </p>
      )}
      {submitting && <p className="mt-3 text-small text-text-secondary">Uploading…</p>}
    </Card>
  );
}
