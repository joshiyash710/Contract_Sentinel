import { redirect } from "next/navigation";

// The Contracts nav entry is the upload flow (spec 015 D5). redirect() throws a control-flow
// signal by design — call it at the top level, never inside try/catch.
export default function ContractsPage() {
  redirect("/upload");
}
