import { TopBar } from "@/components/shell/TopBar";
import { UploadForm } from "@/components/upload/UploadForm";

export default function UploadPage() {
  return (
    <>
      <TopBar title="Contract Upload" />
      <div className="flex justify-center p-6 pt-12">
        <UploadForm />
      </div>
    </>
  );
}
