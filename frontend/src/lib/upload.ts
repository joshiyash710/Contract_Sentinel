/**
 * Client-side upload validation (spec 015 §2.3 D1). Mirrors the 011 boundary constants so the
 * UX rejects bad files early; the server (011 AC-15/AC-16, EC-5) remains authoritative.
 */
export const ACCEPTED_EXTENSIONS = [".pdf", ".docx"] as const; // mirrors 011 ALLOWED_UPLOAD_EXTENSIONS
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024; // mirrors 011 MAX_UPLOAD_SIZE_BYTES (25 MB)
export const ACCEPT_ATTR = ".pdf,.docx"; // for <input accept="…">

export type FileError = "type" | "size" | "empty";

export type FileValidation = { ok: true } | { ok: false; error: FileError; message: string };

export function validateFile(file: File): FileValidation {
  const lower = file.name.toLowerCase();
  const okExt = ACCEPTED_EXTENSIONS.some((e) => lower.endsWith(e));
  if (!okExt) return { ok: false, error: "type", message: "Only PDF and DOCX files are supported." };
  if (file.size === 0) return { ok: false, error: "empty", message: "That file is empty." };
  if (file.size > MAX_UPLOAD_BYTES) return { ok: false, error: "size", message: "File exceeds the 25 MB limit." };
  return { ok: true };
}
