"use client";

import clsx from "clsx";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { ACCEPT_ATTR } from "@/lib/upload";

const FILE_TYPES = [
  { label: "PDF", color: "bg-risk-high" },
  { label: "DOCX", color: "bg-accent-gradient-to" },
];

/**
 * Dashed drag-&-drop zone (screen 9). Shows PDF + DOCX type chips (no TXT — spec D1), a hidden
 * file input, and a Browse button. Both drop and browse funnel through a single `onFile` prop so
 * the two paths are identical (spec AC-3). Validation + submit live in UploadForm.
 */
export function DropZone({ onFile, disabled = false }: { onFile: (f: File) => void; disabled?: boolean }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);

  const handleFiles = (files: FileList | null) => {
    if (disabled || !files || files.length === 0) return;
    onFile(files[0]);
  };

  return (
    <div>
      <div
        data-testid="dropzone"
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragActive(false);
          handleFiles(e.dataTransfer.files);
        }}
        className={clsx(
          "rounded-card border-2 border-dashed p-8 text-center transition",
          dragActive ? "border-accent bg-card-raised/50" : "border-subtle",
          disabled && "opacity-60",
        )}
      >
        <div className="mb-4 flex items-center justify-center gap-3">
          {FILE_TYPES.map((t) => (
            <span
              key={t.label}
              className={clsx(
                "flex h-14 w-12 items-center justify-center rounded-lg text-caption font-bold text-white",
                t.color,
              )}
            >
              {t.label}
            </span>
          ))}
        </div>
        <p className="text-body text-text-secondary">
          Drag &amp; Drop files here, or{" "}
          <button
            type="button"
            disabled={disabled}
            onClick={() => inputRef.current?.click()}
            className="text-accent underline-offset-2 hover:underline disabled:no-underline"
          >
            browse
          </button>
          .
        </p>
        <input
          ref={inputRef}
          data-testid="file-input"
          type="file"
          accept={ACCEPT_ATTR}
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>
      <Button
        variant="primary"
        disabled={disabled}
        className="mt-4 w-full"
        onClick={() => inputRef.current?.click()}
      >
        Browse Files
      </Button>
    </div>
  );
}
