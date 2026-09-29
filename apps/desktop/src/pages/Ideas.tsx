import { CampaignPicker, useCampaignParam } from "../components/CampaignPicker";
import IdeaList from "../components/IdeaList";
import { Card, Empty, Page } from "../components/ui";
import { useApi } from "../hooks";
import type { Idea } from "../types";

export default function IdeasPage() {
  const [campaignId, setCampaignId, campaigns] = useCampaignParam();
  const ideas = useApi<Idea[]>(campaignId ? `/api/campaigns/${campaignId}/ideas` : null);
  return (
    <Page title="Ideas" subtitle="Ten deliberately different concept categories per campaign. Scores are computed locally, not self-reported by the AI.">
      <CampaignPicker value={campaignId} onChange={setCampaignId} campaigns={campaigns} />
      {campaigns && campaigns.length === 0 ? (
        <Empty>Create a campaign first.</Empty>
      ) : (
        campaignId && (
          <Card>
            <IdeaList key={campaignId} campaignId={campaignId} ideas={ideas.data ?? []} reload={ideas.reload} />
          </Card>
        )
      )}
    </Page>
  );
}
