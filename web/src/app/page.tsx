import { App } from "@/components/App";

// NEXT_PUBLIC_API_URL empty or unset: mock mode on the example payloads. Set it to use the API.
export default function Page() {
  return <App baseUrl={process.env.NEXT_PUBLIC_API_URL ?? ""} />;
}
