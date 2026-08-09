import { Shield } from "lucide-react";

/**
 * Animated processing centerpiece (screen 6). Pure presentation — no data/API. A soft pulsing
 * halo, a slowly rotating dashed orbit ring with three colored glow dots, and a gently floating
 * light "document" (placeholder text lines top & bottom around a glowing shield badge) whose
 * surface is swept by a scanning line. All motion is token-driven CSS and fully disabled under
 * prefers-reduced-motion (.proc-art).
 */
export function ProcessingArt() {
  return (
    <div className="proc-art relative flex h-72 w-72 items-center justify-center" aria-hidden="true">
      {/* soft pulsing halo */}
      <div className="absolute h-52 w-52 rounded-full bg-accent/15 blur-3xl [animation:halo_4.5s_ease-in-out_infinite]" />

      {/* faint outer ring + slowly rotating dashed orbit ring */}
      <div className="absolute h-72 w-72 rounded-full border border-white/[0.05]" />
      <div className="absolute h-64 w-64 rounded-full border border-dashed border-white/12 animate-spin [animation-duration:34s]" />

      {/* three colored glow dots pinned around the ring, gently pulsing */}
      <span className="absolute left-1/2 top-2 h-3 w-3 -translate-x-1/2 rounded-full bg-[color:var(--accent-cyan)] shadow-[0_0_16px_var(--accent-cyan)] [animation:dot-pulse_2.4s_ease-in-out_infinite]" />
      <span className="absolute right-4 top-[34%] h-2.5 w-2.5 rounded-full bg-[color:var(--accent-gradient-to)] shadow-[0_0_14px_var(--accent-gradient-to)] [animation:dot-pulse_2.4s_ease-in-out_0.5s_infinite]" />
      <span className="absolute bottom-8 left-10 h-3 w-3 rounded-full bg-accent shadow-[0_0_16px_var(--accent)] [animation:dot-pulse_2.4s_ease-in-out_1s_infinite]" />

      {/* floating light document */}
      <div className="float-slow relative z-10">
        <div className="relative flex h-52 w-44 flex-col justify-between overflow-hidden rounded-2xl border border-white/15 bg-gradient-to-b from-white/[0.14] to-white/[0.04] p-5 shadow-[0_34px_80px_-24px_rgba(0,0,0,0.8)] backdrop-blur-xl">
          {/* scanning sweep */}
          <div className="pointer-events-none absolute inset-x-0 top-0 h-1/3 bg-gradient-to-b from-accent/25 via-accent/10 to-transparent [animation:scan_3s_var(--ease-expo)_infinite]" />

          {/* top text lines */}
          <div className="space-y-2">
            <div className="h-2 w-3/4 rounded-full bg-white/25" />
            <div className="h-2 w-1/2 rounded-full bg-white/15" />
          </div>

          {/* glowing shield badge, centered */}
          <div className="relative mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-gradient shadow-glow">
            <div className="absolute inset-0 rounded-2xl bg-accent/40 blur-md [animation:halo_3s_ease-in-out_infinite]" />
            <Shield size={26} className="relative text-accent-fg" />
          </div>

          {/* bottom text lines */}
          <div className="space-y-2">
            <div className="h-2 w-full rounded-full bg-white/15" />
            <div className="h-2 w-5/6 rounded-full bg-white/12" />
            <div className="h-2 w-2/3 rounded-full bg-white/10" />
          </div>
        </div>
      </div>
    </div>
  );
}
