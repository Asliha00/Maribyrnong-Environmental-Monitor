import { useQuery } from "@tanstack/react-query";
import { getHealth } from "../api/client";

/** Small status indicator proving the frontend reaches the API on the same origin. */
export default function HealthBadge() {
  const { data, isError, isPending } = useQuery({ queryKey: ["health"], queryFn: getHealth });
  let label = "Checking service…";
  if (isError) label = "Service unavailable";
  else if (!isPending) label = data.database === "ok" ? "Service online" : "Database unavailable";
  return <span role="status">{label}</span>;
}
