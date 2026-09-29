import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useApi } from "../hooks";
import type { Campaign } from "../types";
import { Field } from "./ui";

/** Campaign selector kept in the URL (?campaign=) so pages can be linked and reopened. */
export function useCampaignParam(): [string, (id: string) => void, Campaign[] | null] {
  const [params, setParams] = useSearchParams();
  const { data } = useApi<Campaign[]>("/api/campaigns");
  const current = params.get("campaign") ?? "";
  useEffect(() => {
    if (!current && data && data.length > 0) setParams({ campaign: data[0].id }, { replace: true });
  }, [current, data, setParams]);
  return [current, (id: string) => setParams(id ? { campaign: id } : {}), data];
}

export function CampaignPicker({ value, onChange, campaigns }: { value: string; onChange: (id: string) => void; campaigns: Campaign[] | null }) {
  return (
    <Field label="Campaign">
      <select value={value} onChange={(e) => onChange(e.target.value)} style={{ minWidth: 280 }}>
        {(campaigns ?? []).map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
    </Field>
  );
}
