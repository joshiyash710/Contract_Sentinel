import { Avatar } from "@/components/ui/Avatar";

/**
 * Sidebar-bottom profile block (avatar + name + role). Renders from PROPS / placeholder — no
 * auth backend is called (spec AC-5). Never bakes a mockup name (spec EC-5).
 */
export function UserProfileBlock({
  name,
  role,
  avatarSrc,
}: {
  name: string;
  role?: string;
  avatarSrc?: string;
}) {
  return (
    <div className="flex items-center gap-3 border-t border-subtle px-4 py-4">
      <Avatar name={name} src={avatarSrc} size="md" />
      <div className="min-w-0">
        <div className="truncate text-body font-medium text-text-primary">{name}</div>
        {role ? <div className="truncate text-small text-text-secondary">{role}</div> : null}
      </div>
    </div>
  );
}
