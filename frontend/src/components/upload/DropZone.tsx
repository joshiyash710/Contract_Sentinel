"use client";

import clsx from "clsx";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { ACCEPT_ATTR } from "@/lib/upload";

const FILE_TYPES = [
  { label: "PDF", color: "bg-risk-high" },
  // MS Word blue so the DOCX chip reads as the official Word logo (matching PDF's Adobe red).
  { label: "DOCX", color: "bg-brand-word" },
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
        <div className="mb-5 flex items-center justify-center gap-4">
          {FILE_TYPES.map((t, i) => (
            <span
              key={t.label}
              style={{ transform: `rotate(${(i - 0.5) * 6}deg)` }}
              className={clsx(
                "flex h-20 w-16 items-center justify-center rounded-2xl text-small font-bold text-white shadow-lg shadow-black/30",
                t.color,
              )}
            >
              {t.label}
            </span>
          ))}
        </div>
        <p className="text-h3 font-semibold text-text-primary">Drag &amp; drop your contract here</p>
        <p className="mt-1 text-small text-text-secondary">
          or{" "}
          <button
            type="button"
            disabled={disabled}
            onClick={() => inputRef.current?.click()}
            className="font-medium text-accent underline-offset-2 hover:underline disabled:no-underline"
          >
            browse
          </button>{" "}
          files from your computer
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
